from pathlib import Path

from fastapi.testclient import TestClient

from hardware_readiness_api import create_hardware_readiness_app


ROOT = Path(__file__).resolve().parents[1]


def test_hardware_readiness_context_is_fixture_backed_and_read_only():
    client = TestClient(create_hardware_readiness_app())

    response = client.get("/admin/hardware-readiness/context?selected_provider_ref=provider.gnss.primary")

    assert response.status_code == 200
    payload = response.json()
    assert payload["surface"] == "hardware_readiness"
    assert payload["read_only"] is True
    assert payload["summary"]["provider_count"] == 2
    assert payload["summary"]["degraded_provider_count"] == 1
    assert payload["selected_provider"]["provider_ref"] == "provider.gnss.primary"
    assert payload["boundary"]["hardware_control_allowed"] is False
    assert payload["boundary"]["provider_control_allowed"] is False
    assert payload["boundary"]["outbound_send_allowed"] is False
    assert payload["boundary"]["real_sos_allowed"] is False


def test_hardware_readiness_admin_page_serves_static_shell_and_shared_script():
    client = TestClient(create_hardware_readiness_app())

    page = client.get("/admin/hardware-readiness")
    script = client.get("/admin/scout-assistant-ui.js")

    assert page.status_code == 200
    assert "Scout Hardware Readiness" in page.text
    assert "data-assistant-surface=\"hardware_readiness\"" in page.text
    assert "read-only model interpretation" in page.text
    assert "/assistant/query" in page.text
    assert "/assistant/status" in page.text
    assert "/admin/hardware-readiness/context" in page.text
    assert "No hardware control or provider control." in page.text
    assert "No real SOS, SMS, satellite, or outbound transport." in page.text
    assert script.status_code == 200
    assert "window.ScoutAssistantUI" in script.text


def test_hardware_readiness_api_has_no_mutation_methods():
    client = TestClient(create_hardware_readiness_app())

    assert client.post("/admin/hardware-readiness/context", json={}).status_code == 405
    assert client.patch("/admin/hardware-readiness/context", json={}).status_code == 405
    assert client.delete("/admin/hardware-readiness/context").status_code == 405

    source = (ROOT / "hardware_readiness_api.py").read_text(encoding="utf-8")
    for forbidden_fragment in (
        "@router.post",
        "@router.patch",
        "@router.put",
        "@router.delete",
        "/safety/",
        "SafetyRuntimeSession",
        "IncidentStore",
        "append_review_decision",
    ):
        assert forbidden_fragment not in source
