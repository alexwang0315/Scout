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
        "fixed read-only `boundary` block",
        "驗證 `radio_counts`",
        "不呼叫 `/safety/observations`",
        "不寫 IncidentStore",
        "不寫 ObservedFact",
        "不寫 Phase 2 Brain",
        "不送 outbound",
        "不控制 hardware provider",
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


def test_runbook_documents_local_admin_assistant_prototype_gate() -> None:
    source = read_runbook()

    for token in (
        "Local Admin / Assistant Prototype Gate",
        "admin_hardware_prototype_smoke_check.py",
        "SCOUT_BROWSER_NODE",
        "SCOUT_BROWSER_NODE_PATH",
        "--browser-mode required",
        "GET /assistant/status",
        "provider 是 `mock`",
        "assistant_ui_smoke_check.py --pretty",
        "assistant_readiness_check.py --pretty",
        "assistant_browser_smoke_check.py --base-url http://127.0.0.1:9111 --pretty",
        "不連 `scout.local`",
        "不啟動 Ollama",
        "不呼叫 `/safety/*` mutation",
        "不控制硬體 provider",
    ):
        assert token in source


def test_runbook_documents_pi_smoke_visual_feedback_wrapper() -> None:
    source = read_runbook()

    for token in (
        "tools/pi_smoke_visual_feedback.py",
        "diagnostic visual feedback",
        "OLED 會顯示 `RUN`",
        "LED Bar 亮前半段",
        "--run-hold-seconds",
        "可讓 RUN 狀態先停留",
        "OLED 顯示 `OK`",
        "LED Bar 全亮",
        "OLED 顯示 `FAIL`",
        "LED Bar 顯示交錯燈號",
        "--require-visual",
        "--visual-dry-run",
        "不呼叫 live `/safety/*` mutation",
        "不送 outbound",
        "不改 Phase 1 safety decision",
    ):
        assert token in source


def test_runbook_documents_gnss_oled_status_summary() -> None:
    source = read_runbook()

    for token in (
        "GNSS NMEA smoke with OLED status",
        "GNSS NMEA smoke with OLED + LED Bar status",
        "--oled-status",
        "--oled-update-seconds 2",
        "--led-status",
        "--led-nofix-bit 1",
        "--led-fix-bit 10",
        "--led-update-seconds 2",
        "--led-blink-count 2",
        "OLED 會顯示 `SCOUT GPS`",
        "`FIX OK` 或 `NO FIX`",
        "Grove LED Bar v2.0 不是 RGB LED",
        "預設 `NO FIX` 閃 LED1",
        "`FIX OK` 閃 LED10",
        "--led-nofix-bit 10 --led-fix-bit 1",
        "diagnostic indicator",
        "NMEA sentence",
        "satellite/fix quality",
        "NMEA signal summary",
        "不呼叫 live `/safety/*` mutation",
        "不送 outbound",
        "不改 Phase 1 safety decision",
    ):
        assert token in source
