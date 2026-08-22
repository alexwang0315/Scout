import json
from pathlib import Path


SERVICE_PATH = Path("deploy/systemd/scout-hailo-ollama.service")
RUNBOOK_PATH = Path("docs/admin/scout-hailo-ollama-service.md")
CONFIG_PATH = Path("configs/assistant-models.dashboard-aihat2.json")


def test_hailo_ollama_user_service_is_boot_persistent_and_local_only() -> None:
    source = SERVICE_PATH.read_text(encoding="utf-8")

    for token in (
        "Description=Scout Hailo Ollama 5.3 local inference service",
        "After=network-online.target",
        "ExecStart=/usr/bin/hailo-ollama",
        "Environment=OLLAMA_HOST=127.0.0.1:8000",
        "Environment=HAILO_OLLAMA_VDEVICE_GROUP_ID=SCOUT_LOCAL_AI",
        "Restart=on-failure",
        "RestartSec=5",
        "NoNewPrivileges=true",
        "PrivateTmp=true",
        "WantedBy=default.target",
    ):
        assert token in source


def test_hailo_ollama_service_runbook_documents_deploy_health_and_rollback() -> None:
    source = RUNBOOK_PATH.read_text(encoding="utf-8")

    for token in (
        "Scout Hailo Ollama 5.3 User Service",
        "loginctl show-user alexwang0315 -p Linger",
        "systemctl --user enable --now scout-hailo-ollama.service",
        "systemctl --user is-active scout-hailo-ollama.service",
        "curl --fail --silent http://127.0.0.1:8000/api/tags",
        "journalctl --user-unit scout-hailo-ollama.service",
        "hailortcli fw-control identify",
        "Firmware Version: 5.3.0",
        "systemctl --user disable --now scout-hailo-ollama.service",
        "phase1_safety_decision_change_allowed=false",
        "remote_outbound_allowed=false",
        "native `tools` request field",
        "deterministic allowlist",
        "http://host.docker.internal:8000",
        "127.0.0.1:18000",
        "Verified Boot Recovery",
        "control characters",
    ):
        assert token in source


def test_dashboard_fallback_config_uses_the_documented_mac_tunnel_endpoint() -> None:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

    assert config["active_profile"] == "cloud"
    assert config["local_model"]["base_url"] == "http://127.0.0.1:18000"
    assert config["local_model"]["backend"] == "hailo_ollama"
    assert config["local_model"]["model_name"] == "hailo:qwen3:1.7b"
    assert config["local_model"]["tool_calling"] == "enabled"
    assert "model_settings" not in config["local_model"]
    assert "model_settings" not in config["cloud_model"]
    assert config["connect_on_startup"] is False
    assert config["fallback_to_local_on_error"] is True
