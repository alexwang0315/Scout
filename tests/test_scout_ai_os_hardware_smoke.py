from __future__ import annotations

import json
from pathlib import Path

from scout.hardware import build_hardware_smoke_profile, run_hardware_smoke


ROOT = Path(__file__).resolve().parents[1]


def test_hardware_smoke_profile_records_all_planned_phases(
    monkeypatch,
) -> None:
    monkeypatch.delenv("SCOUT_AI_OS_MODEL", raising=False)

    profile = build_hardware_smoke_profile(repo_root=ROOT)

    phase_ids = {phase["phase_id"] for phase in profile["phases"]}
    assert phase_ids == {"H0", "H1", "H2", "H3", "H4", "H5", "H6", "H7", "H8"}
    assert profile["boundary"]["hardware_control_allowed"] is False
    assert profile["boundary"]["outbound_send_allowed"] is False
    assert profile["boundary"]["phase1_l0_l4_state_mutation_allowed"] is False
    assert profile["model_policy"]["mode"] == "local_function"


def test_hardware_smoke_default_uses_local_model_and_safe_gates(
    monkeypatch,
) -> None:
    monkeypatch.setenv("SCOUT_AI_OS_MODEL", "glm-5.2")

    report = run_hardware_smoke(repo_root=ROOT)

    checks = {check.check_id: check for check in report.checks}
    assert report.model_policy["mode"] == "local_function"
    assert checks["pydantic_ai_smoke"].status == "passed"
    assert checks["ui_action_smoke"].status == "passed"
    assert checks["notification_dry_run"].evidence["sent"] is False
    assert checks["operator_confirmed_notification_gate"].status == "passed"
    assert checks["operator_confirmed_notification_gate"].evidence["sent"] is True
    assert checks["operator_confirmed_notification_gate"].evidence[
        "telegram_adapter_verified"
    ] is True
    assert checks["sandbox_gate"].status == "passed"
    assert checks["hardware_evidence_boundary"].status == "skipped"
    assert checks["generated_runtime_install_gate"].status == "passed"
    assert checks["generated_runtime_install_gate"].evidence[
        "runtime_install_lifecycle_supported"
    ] is True
    assert checks["generated_runtime_install_gate"].evidence[
        "runtime_dispatch_proof_supported"
    ] is True
    assert checks["generated_runtime_install_gate"].evidence[
        "proof_runtime_code_executed"
    ] is True
    assert checks["generated_runtime_install_gate"].evidence[
        "dispatch_active_runtime_dispatch_enabled"
    ] is False
    assert checks["external_model_sla_gate"].status == "passed"
    assert checks["external_model_sla_gate"].evidence["live_sla_enforced"] is True
    assert checks["external_model_sla_gate"].evidence[
        "circuit_breaker_verified"
    ] is True
    assert report.summary["failed"] == 0
    assert report.summary["runtime_install_ready"] is True
    assert report.summary["generated_runtime_dispatch_proof_ready"] is True
    assert report.summary["generated_runtime_dispatch_ready"] is False
    assert report.summary["live_external_notification_ready"] is True
    assert report.summary["live_external_notification_adapter_ready"] is True
    assert report.summary["live_external_notification_network_verified"] is False
    assert report.summary["external_model_sla_ready"] is True


def test_hardware_smoke_external_model_blocks_without_key(
    monkeypatch,
) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    report = run_hardware_smoke(
        repo_root=ROOT,
        model="glm-5.2",
        allow_external_model=True,
        env_file=ROOT / "missing.env",
    )

    checks = {check.check_id: check for check in report.checks}
    assert report.model_policy["display_name"] == "openrouter:z-ai/glm-5.2"
    assert report.model_policy["missing_credential_env"] == ["OPENROUTER_API_KEY"]
    assert checks["pydantic_ai_smoke"].status == "blocked"
    assert "OPENROUTER_API_KEY" in json.dumps(report.model_dump(mode="json"))


def test_hardware_smoke_accepts_advisory_hardware_evidence(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "evidence.json"
    evidence.write_text(
        json.dumps(
            {
                "artifact_kind": "fixture_hardware_evidence",
                "boundary": {
                    "hardware_control_performed": False,
                    "safety_api_called": False,
                    "phase1_l0_l4_state_mutated": False,
                    "outbound_sent": False,
                },
            }
        ),
        encoding="utf-8",
    )

    report = run_hardware_smoke(repo_root=ROOT, evidence_json=evidence)

    checks = {check.check_id: check for check in report.checks}
    assert checks["hardware_evidence_boundary"].status == "passed"
    assert "phase1_l0_l4_state_mutated" in checks[
        "hardware_evidence_boundary"
    ].evidence["boundary_keys"]


def test_hardware_smoke_blocks_forbidden_hardware_evidence(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "evidence.json"
    evidence.write_text(
        json.dumps(
            {
                "artifact_kind": "bad_hardware_evidence",
                "boundary": {
                    "hardware_control_performed": True,
                    "safety_api_called": False,
                },
            }
        ),
        encoding="utf-8",
    )

    report = run_hardware_smoke(repo_root=ROOT, evidence_json=evidence)

    checks = {check.check_id: check for check in report.checks}
    assert checks["hardware_evidence_boundary"].status == "blocked"
    assert checks["hardware_evidence_boundary"].evidence["forbidden_true"] == {
        "hardware_control_performed": True
    }
