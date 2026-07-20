from __future__ import annotations

import re
import subprocess
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from scout_alpha_simulation_api import create_alpha_simulation_ui_router


ROOT = Path(__file__).resolve().parents[1]
UI_PATH = ROOT / "docs" / "emergency" / "scout-alpha-sandbox-v0.html"


def _html() -> str:
    return UI_PATH.read_text(encoding="utf-8")


def _embedded_javascript(html: str) -> str:
    scripts = re.findall(r"<script(?:\s[^>]*)?>(.*?)</script>", html, re.DOTALL)
    assert scripts, "Alpha Sandbox must include its self-contained JavaScript"
    return "\n".join(scripts)


def test_alpha_sandbox_operator_surface_contract() -> None:
    html = _html()

    assert 'data-alpha-sandbox-version="v0"' in html
    assert 'data-synthetic="true"' in html
    assert "Synthetic replay" in html
    assert "Candidate only" in html
    assert "Not runtime safety truth" in html
    assert "No real transport or delivery occurs" in html
    assert "請勿貼入真實個資、精確位置、健康資料或密鑰" in html
    assert "artifact 僅保存去識別標記與雜湊" in html

    for control in (
        "scenarioSelect",
        "prepareRun",
        "stepRun",
        "runToCompletion",
        "networkOffline",
        "networkOnline",
        "gnssStale",
        "gnssDropout",
        "gnssJump",
        "wearableOffline",
        "wearableLowBattery",
        "textCommand",
        "sendTextSimulation",
        "voiceTranscript",
        "sendVoiceSimulation",
        "approveSimulatedSend",
        "declineCandidate",
        "recordSimulatedReceipt",
    ):
        assert f'id="{control}"' in html

    for panel in (
        "workspacePanel",
        "timelinePanel",
        "devicePanel",
        "gatePanel",
        "livingPanel",
    ):
        assert f'id="{panel}"' in html

    assert "Workspace / GPX source" in html
    assert "Fault injection" in html
    assert "Text command simulation" in html
    assert "Voice transcript simulation" in html
    assert 'aria-live="polite"' in html
    assert ":focus-visible" in html
    assert "min-height: 44px" in html
    assert "@media (max-width: 760px)" in html


def test_alpha_sandbox_calls_only_same_origin_alpha_endpoints() -> None:
    html = _html()

    for endpoint in (
        '"/admin/dashboard/living/alpha/scenarios"',
        '"/admin/dashboard/living/alpha"',
        '"/admin/dashboard/living/alpha/runs"',
        '"/admin/dashboard/living/alpha/advance"',
        '"/admin/dashboard/living/alpha/interactions"',
        '"/admin/dashboard/living/alpha/approvals"',
        '"/admin/dashboard/living/alpha/transport/simulations"',
    ):
        assert endpoint in html

    assert "ALLOWED_ENDPOINTS" in html
    assert "credentials: \"same-origin\"" in html
    assert "assertAllowedEndpoint" in html
    assert "method: \"POST\"" in html

    for forbidden in (
        "/safety/",
        "http://",
        "https://",
        "XMLHttpRequest",
        "WebSocket",
        "EventSource",
        "sendBeacon",
        "navigator.geolocation",
        "navigator.mediaDevices",
        "SpeechRecognition",
        "/Users/",
        ".env",
    ):
        assert forbidden not in html


def test_alpha_sandbox_payloads_and_projection_keep_safety_boundaries_explicit() -> None:
    html = _html()

    for token in (
        "candidate_only: true",
        "runtime_safety_truth: false",
        "synthetic_replay: true",
        "real_outbound_send_performed: false",
        "hardware_control_invoked: false",
        "phase1_l0_l4_state_mutated: false",
        "confirm_sandbox_run: true",
        "confirm_sandbox_advance: true",
        "confirm_sandbox_interaction: true",
        "confirm_sandbox_action: true",
        "confirm_simulated_transport: true",
        'ingress_mode: "loopback_mqtt_broker"',
        'channel: "ui_action"',
        'channel: "text"',
        'channel: "voice"',
        'kind: "command"',
        'kind: "voice_transcript"',
        'content: "fault.network.offline"',
        'content: "fault.gnss.stale"',
        'content: "fault.wearable.offline"',
        'decision: "agree_send"',
        'decision: "do_not_send"',
        'outcome: "simulated_receipt_recorded"',
        "run_defaults.workspace_configured",
        "run_defaults.project_id",
        "run_defaults.gpx_ref",
        "sharedDefaults",
    ):
        assert token in html

    assert "runToCompletion" in html
    assert 'mode: "step"' in html
    assert 'mode: "run_to_completion"' in html
    assert "renderTimeline" in html
    assert "replayEvents" in html
    assert '"virtual_at"' in html
    assert "renderDevices" in html
    assert "renderGates" in html
    assert "renderLiving" in html


def test_alpha_sandbox_embedded_javascript_parses() -> None:
    script = _embedded_javascript(_html())
    completed = subprocess.run(
        ["node", "--check", "-"],
        input=script,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr


def test_alpha_sandbox_page_sets_local_prototype_browser_headers() -> None:
    app = FastAPI()
    app.include_router(create_alpha_simulation_ui_router())

    response = TestClient(app).get("/emergency/sandbox-alpha-v0")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"
