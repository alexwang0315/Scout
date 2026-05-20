from __future__ import annotations

import re
from pathlib import Path


RUNBOOK_PATH = Path("docs/admin/scout-machine-deployment-smoke.md")


def read_runbook() -> str:
    return RUNBOOK_PATH.read_text(encoding="utf-8")


def test_scout_machine_deployment_smoke_runbook_is_chinese_first() -> None:
    source = read_runbook()
    cjk_chars = re.findall(r"[\u4e00-\u9fff]", source)
    latin_words = re.findall(r"[A-Za-z]{2,}", source)

    assert len(cjk_chars) > 450
    assert len(cjk_chars) > len(latin_words)
    assert "這份 runbook 是 hardware prototype prep 的人工 smoke 測試指南" in source


def test_runbook_keeps_prototype_prep_offline_until_operator_runs_manual_steps() -> None:
    source = read_runbook()

    for token in (
        "offline preflight",
        "不連 Pi",
        "不啟動 Docker",
        "不啟動 Ollama",
        "不啟動本地模型",
        "不呼叫 live `/safety/*` mutation",
        "不送 outbound",
        "不控制 hardware provider",
        "manual-only",
    ):
        assert token in source


def test_runbook_documents_step1_environment_and_manual_smoke_ladder() -> None:
    source = read_runbook()

    for token in (
        "SCOUT_DATA_ROOT=/data/scout",
        "SCOUT_RUNTIME_PROFILE=pi-field",
        "SCOUT_ENABLE_LIVE_HARDWARE=0",
        "SCOUT_ENABLE_AI_INFERENCE=0",
        "SCOUT_EVENT_BUS=none",
        "curl --max-time 5 http://scout.local:9099/health",
        "curl --max-time 5 http://scout.local:9099/runtime/status",
        "curl --max-time 5 http://scout.local:9099/providers/status",
        "http://scout.local:9099/safety/observations",
    ):
        assert token in source


def test_runbook_documents_host_side_radio_scan_boundary() -> None:
    source = read_runbook()

    for token in (
        "tools/pi_radio_scan_smoke.py",
        "radio_environment_scan",
        "/data/scout/providers/radio_scan/manual-smoke.jsonl",
        "不呼叫 `/safety/observations`",
        "不寫 IncidentStore",
        "不寫 ObservedFact",
        "不寫 Phase 2 Brain",
        "不控制 Phase 1 safety decision",
    ):
        assert token in source


def test_runbook_links_focused_local_validation_command() -> None:
    source = read_runbook()

    assert (
        "/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest "
        "tests/test_scout_hardware_prototype_prep.py "
        "tests/test_scout_machine_deployment_smoke_runbook.py"
    ) in source
