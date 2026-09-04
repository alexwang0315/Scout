from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from scout.hardware.old_pc_debug_link import (
    OldPcDebugReceiptStore,
    OldPcDebugSignal,
    build_old_pc_debug_watchdog_result,
    build_simulated_old_pc_report,
    create_old_pc_debug_app,
    old_pc_debug_boundary,
)


@pytest.mark.parametrize(
    "script_name",
    ["scout_old_pc_debug_agent.py", "scout_old_pc_debug_loopback_smoke.py"],
)
def test_old_pc_debug_cli_starts_outside_repository(
    tmp_path: Path, script_name: str
) -> None:
    script = Path(__file__).resolve().parents[1] / "tools" / script_name
    result = subprocess.run(
        [sys.executable, str(script), "--help"],
        cwd=tmp_path,
        env={"PYTHONPATH": ""},
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stderr
    assert "usage:" in result.stdout


def test_received_old_pc_debug_report_proves_headless_usable_path(tmp_path: Path) -> None:
    store = OldPcDebugReceiptStore(tmp_path)
    report = build_simulated_old_pc_report(subject_ref="haswell-candidate")

    receipt = store.ingest(report)
    latest = json.loads(store.latest_receipt_path.read_text(encoding="utf-8"))
    jsonl_lines = store.receipt_jsonl_path.read_text(encoding="utf-8").splitlines()

    assert receipt.disposition == "USABLE_HEADLESS"
    assert receipt.transport_received is True
    assert receipt.report.lan.status == "missing"
    assert receipt.report.display.status == "missing"
    assert receipt.boundary["debug_evidence_write_performed"] is True
    assert receipt.boundary["phase1_l0_l4_state_mutated"] is False
    assert receipt.boundary["safety_api_called"] is False
    assert latest["receipt_id"] == receipt.receipt_id
    assert len(jsonl_lines) == 1


def test_watchdog_retires_old_pc_when_no_report_arrives() -> None:
    result = build_old_pc_debug_watchdog_result(
        None,
        subject_ref="haswell-candidate",
        timeout_seconds=60,
    )

    assert result.status == "report_missing"
    assert result.disposition == "RETIRE"
    assert "No old-PC debug-agent report reached Scout" in result.decision_reasons[0]
    assert result.boundary["hardware_control_performed"] is False
    assert result.boundary["outbound_sent"] is False


def test_critical_storage_report_retires_after_receipt(tmp_path: Path) -> None:
    report = build_simulated_old_pc_report(subject_ref="haswell-candidate").model_copy(
        update={
            "storage": OldPcDebugSignal(
                status="critical",
                summary="root filesystem has critically low free space",
                evidence={"free_percent": 1.2},
            )
        }
    )

    receipt = OldPcDebugReceiptStore(tmp_path).ingest(report)

    assert receipt.disposition == "RETIRE"
    assert any("Critical post-boot hardware risk" in reason for reason in receipt.decision_reasons)


def test_old_pc_debug_api_accepts_safe_report_and_rejects_runtime_effects(tmp_path: Path) -> None:
    client = TestClient(create_old_pc_debug_app(evidence_dir=tmp_path))
    report_payload = build_simulated_old_pc_report(subject_ref="haswell-candidate").model_dump(
        mode="json"
    )

    response = client.post("/hardware/old-pc-debug/reports", json=report_payload)
    latest = client.get("/hardware/old-pc-debug/latest")

    assert response.status_code == 200
    assert response.json()["disposition"] == "USABLE_HEADLESS"
    assert latest.status_code == 200
    assert latest.json()["receipt_id"] == response.json()["receipt_id"]

    unsafe_payload = {
        **report_payload,
        "boundary": old_pc_debug_boundary() | {"hardware_control_performed": True},
    }
    unsafe = client.post("/hardware/old-pc-debug/reports", json=unsafe_payload)

    assert unsafe.status_code == 400
    assert "runtime effects" in unsafe.json()["detail"]


def test_old_pc_debug_boundary_rejects_secret_inclusion_flag() -> None:
    with pytest.raises(ValueError):
        old_pc_debug_boundary(secret_values_included=True)
