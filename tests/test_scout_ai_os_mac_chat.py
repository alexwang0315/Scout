from __future__ import annotations

import json
from typing import Any
from urllib.error import URLError

from fastapi.testclient import TestClient

from scout.mac_chat import create_mac_chat_app
from scout.mac_chat.client import ScoutServerClient, normalize_server_url


class _FakeResponse:
    def __init__(self, payload: dict[str, Any], *, status: int = 200) -> None:
        self.payload = payload
        self.status = status

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def test_mac_chat_serves_static_interface() -> None:
    client = TestClient(create_mac_chat_app(target_url="http://scout.local:9120"))

    index = client.get("/")
    script = client.get("/static/app.js")
    styles = client.get("/static/styles.css")

    assert index.status_code == 200
    assert "Scout AI" in index.text
    assert "Conversation" in index.text
    assert "server-panel" in index.text
    assert script.status_code == 200
    assert "/api/chat" in script.text
    assert styles.status_code == 200
    assert ".assistant" in styles.text or ".message.assistant" in styles.text


def test_mac_chat_reports_hardware_server_capabilities() -> None:
    def fake_urlopen(request: Any, *, timeout: float) -> _FakeResponse:
        assert timeout == 8.0
        assert request.full_url == "http://scout.local:9120/capabilities"
        return _FakeResponse(
            {
                "capabilities": [
                    {"name": "manual_notification"},
                    {"name": "scout.ui.action_plan"},
                ]
            }
        )

    scout_client = ScoutServerClient(
        "http://scout.local:9120",
        urlopen_func=fake_urlopen,
    )
    client = TestClient(create_mac_chat_app(scout_client=scout_client))

    response = client.get("/api/server")

    assert response.status_code == 200
    payload = response.json()
    assert payload["connected"] is True
    assert payload["target_url"] == "http://scout.local:9120"
    assert payload["capability_count"] == 2
    assert payload["ui_action_capability_present"] is True


def test_mac_chat_posts_requests_to_scout_hardware_server() -> None:
    seen_payloads: list[dict[str, Any]] = []

    def fake_urlopen(request: Any, *, timeout: float) -> _FakeResponse:
        del timeout
        assert request.full_url == "http://scout.local:9120/requests"
        seen_payloads.append(json.loads(request.data.decode("utf-8")))
        return _FakeResponse(
            {
                "status": "ui_action_planned",
                "workflow_id": None,
                "message": "UI action is allowed as session-local state only.",
                "route": {
                    "route_class": "ui_operation",
                    "tool_id": "scout.ui.action_plan",
                    "permission": {
                        "allowed": True,
                        "requires_user_approval": False,
                        "reason": "session-local UI action",
                        "user_message": "UI action is allowed as session-local state only.",
                    },
                },
                "ui_action_plan": {
                    "status": "planned",
                    "actions": [
                        {
                            "action_kind": "set_layer_preset",
                            "label": "Show only Scout risk layers",
                            "preset_id": "risk_only",
                            "visible_layers": [
                                "risk-score",
                                "risk-ribbon",
                                "risk-heatmap",
                                "risk-delta",
                            ],
                            "requires_confirmation": False,
                            "session_only": True,
                        }
                    ],
                },
            }
        )

    scout_client = ScoutServerClient(
        "http://scout.local:9120",
        urlopen_func=fake_urlopen,
    )
    client = TestClient(create_mac_chat_app(scout_client=scout_client))

    response = client.post(
        "/api/chat",
        json={
            "message": "請幫我關掉所有地圖圖層，只留下 risk score 相關圖層。",
            "user_id": "mac-user",
            "surface": "pretrip",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["summary"]["status"] == "ui_action_planned"
    assert payload["summary"]["tool_id"] == "scout.ui.action_plan"
    assert payload["summary"]["action_kind"] == "set_layer_preset"
    assert seen_payloads[0]["user_id"] == "mac-user"
    assert seen_payloads[0]["active_context"]["surface"] == "pretrip"
    assert seen_payloads[0]["active_context"]["client"] == "scout_mac_chat"


def test_mac_chat_surfaces_remote_disconnect_without_fallback() -> None:
    def fake_urlopen(_request: Any, *, timeout: float) -> _FakeResponse:
        del timeout
        raise URLError("connection refused")

    scout_client = ScoutServerClient(
        "http://scout.local:9120",
        urlopen_func=fake_urlopen,
    )
    client = TestClient(create_mac_chat_app(scout_client=scout_client))

    response = client.post(
        "/api/chat",
        json={"message": "Remind me in 10 minutes.", "surface": "pretrip"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    assert payload["summary"]["status"] == "disconnected"
    assert payload["response"] == {}
    assert "Scout server unavailable" in payload["error"]


def test_normalize_server_url_rejects_non_http_urls() -> None:
    assert normalize_server_url("http://scout.local:9120/") == "http://scout.local:9120"

    try:
        normalize_server_url("file:///tmp/scout.sock")
    except ValueError as exc:
        assert "http(s)" in str(exc)
    else:
        raise AssertionError("non-http URL should be rejected")
