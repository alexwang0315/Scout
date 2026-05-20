import re
from pathlib import Path


RUNBOOK_PATH = Path("docs/admin/hardware-readiness-assistant-runbook.md")


def read_runbook() -> str:
    return RUNBOOK_PATH.read_text(encoding="utf-8")


def test_hardware_readiness_runbook_is_chinese_first() -> None:
    source = read_runbook()
    cjk_chars = re.findall(r"[\u4e00-\u9fff]", source)
    latin_words = re.findall(r"[A-Za-z]{2,}", source)

    assert len(cjk_chars) > 350
    assert len(cjk_chars) > len(latin_words)
    assert "這份 runbook 是 Slice 22 的 hardware readiness assistant 操作邊界" in source


def test_runbook_documents_fixture_backed_read_only_surfaces() -> None:
    source = read_runbook()

    for token in (
        "/admin/hardware-readiness",
        "/admin/hardware-readiness/context",
        "fixture-backed/read-only",
        "`fixture-backed`",
        "`read-only`",
        "`GET`",
        "`POST`",
        "`PUT`",
        "`PATCH`",
        "`DELETE`",
        "read-only model interpretation",
    ):
        assert token in source


def test_runbook_blocks_live_hardware_and_provider_control() -> None:
    source = read_runbook()

    for token in (
        "不啟動 Pi",
        "不啟動 Docker",
        "不啟動 k3s",
        "不啟動 MQTT",
        "不啟動 NATS",
        "不啟動 Coral",
        "不啟動 Jetson",
        "不控制 provider",
        "不控制 assistant provider",
        "不切換 model provider",
        "不讀取 token value",
    ):
        assert token in source


def test_runbook_blocks_outbound_safety_and_state_mutations() -> None:
    source = read_runbook()

    for token in (
        "不送真 SOS",
        "不送真 SMS",
        "不送真 satellite",
        "不送任何 real outbound transport",
        "不呼叫 `/safety/*` mutation",
        "不寫 ObservedFact",
        "不寫 Brain",
        "不寫 Phase 2 Brain",
        "不寫 IncidentStore",
        "不寫 review decision",
        "不核准 departure",
        "不產生 Final MissionGraph",
        "不啟動 runtime handoff",
    ):
        assert token in source


def test_runbook_includes_focused_acceptance_command() -> None:
    source = read_runbook()

    assert "/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest tests/test_hardware_readiness_runbook.py" in source
    assert "tests/test_hardware_readiness_api.py" in source
