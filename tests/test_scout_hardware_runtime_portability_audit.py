from __future__ import annotations

import re
from pathlib import Path


AUDIT_PATH = Path("docs/admin/scout-hardware-runtime-portability-audit.md")


def read_audit() -> str:
    return AUDIT_PATH.read_text(encoding="utf-8")


def test_portability_audit_is_chinese_first_and_step1_scoped() -> None:
    source = read_audit()
    cjk_chars = re.findall(r"[\u4e00-\u9fff]", source)
    latin_words = re.findall(r"[A-Za-z]{2,}", source)

    assert len(cjk_chars) > 650
    assert len(cjk_chars) > len(latin_words)
    assert "這份 audit 是 hardware-port Slice 1 的部署前盤點" in source
    assert "Pi 5 + Docker + `/data/scout`" in source


def test_audit_classifies_runtime_modules_and_workstation_modules() -> None:
    source = read_audit()

    for token in (
        "`runtime-core`",
        "`optional-provider`",
        "`admin-workstation`",
        "`test-dev`",
        "`ai-experimental`",
        "safety_api.py",
        "safety_runtime_session.py",
        "route_progress.py",
        "incident_store.py",
        "observation_adapter.py",
        "macos_wifi.py",
        "assistant_api.py",
        "debug_api.py",
    ):
        assert token in source


def test_audit_documents_blockers_and_non_goals() -> None:
    source = read_audit()

    for token in (
        "macOS-only",
        "workstation-only",
        "PdrSample",
        "Phase 4",
        "不改 Phase 1 safety decision",
        "不把本地模型放進 Step 1 runtime-core",
        "不啟動 Ollama",
        "不接 k3s、MQTT、NATS、Coral、Jetson",
        "不送 outbound",
    ):
        assert token in source


def test_audit_lists_verification_ladder_without_live_hardware() -> None:
    source = read_audit()

    for token in (
        "tests/test_scout_hardware_prototype_prep.py",
        "tests/test_scout_machine_deployment_smoke_runbook.py",
        "tests/test_safety_runtime_session.py",
        "tests/test_safety_api.py",
        "phase2_release_check.py",
        "不連 Pi",
        "不控制真硬體",
        "不呼叫 live `/safety/*` mutation",
    ):
        assert token in source
