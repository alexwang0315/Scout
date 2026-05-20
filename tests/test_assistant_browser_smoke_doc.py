from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOC_PATH = ROOT / "docs" / "admin" / "assistant-browser-smoke.md"
SCREENSHOT_PATHS = (
    ROOT / "docs" / "admin" / "screenshots" / "assistant-browser-smoke-debug.jpg",
    ROOT / "docs" / "admin" / "screenshots" / "assistant-browser-smoke-pretrip.jpg",
    ROOT / "docs" / "admin" / "screenshots" / "assistant-browser-smoke-admin.jpg",
    ROOT / "docs" / "admin" / "screenshots" / "assistant-browser-smoke-hardware-readiness.jpg",
    ROOT / "docs" / "admin" / "screenshots" / "assistant-browser-live-debug.jpg",
    ROOT / "docs" / "admin" / "screenshots" / "assistant-browser-live-pretrip.jpg",
    ROOT / "docs" / "admin" / "screenshots" / "assistant-browser-live-admin.jpg",
    ROOT / "docs" / "admin" / "screenshots" / "assistant-browser-live-hardware-readiness.jpg",
)


def test_browser_smoke_doc_covers_all_assistant_surfaces_and_boundaries() -> None:
    source = DOC_PATH.read_text(encoding="utf-8")

    for token in (
        "browser-backed visual QA",
        "read-only model interpretation",
        "/assistant/query",
        "/assistant/status",
        "http://127.0.0.1:9110/admin/debug",
        "http://127.0.0.1:9110/admin/pretrip",
        "http://127.0.0.1:9110/admin",
        "http://127.0.0.1:9110/admin/hardware-readiness",
        "不呼叫 `/safety/*` mutation",
        "不寫 ObservedFact",
        "不寫 Phase 2 Brain",
        "不寫 IncidentStore",
        "不接受或拒絕 pretrip candidate",
        "不送 outbound message",
        "不控制 hardware",
        "不啟動本地模型",
        "11434",
        "cloud_only",
        "local_fallback_enabled",
        "token_values_exposed",
        "Offline Fallback Responsive Recheck",
        "SCOUT_PORT=9111",
        "SCOUT_SAFETY_ENABLED=false",
        "SCOUT_AI_ASSISTANT_PROVIDER=mock",
        "provider=mock",
        "startup_connection_status=not_checked",
        "1440x1000",
        "390x844",
        "horizontalOverflowPx=0",
        "Post-analysis overview",
        "section count from 14 to 4",
        "assistantPanel overflowY=auto",
        "console/page errors",
    ):
        assert token in source


def test_browser_smoke_screenshots_exist_and_are_jpegs() -> None:
    for path in SCREENSHOT_PATHS:
        data = path.read_bytes()

        assert len(data) > 1024, path
        assert data.startswith(b"\xff\xd8\xff"), path
