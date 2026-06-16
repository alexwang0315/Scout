from __future__ import annotations

from pathlib import Path

from ingress_observer_supervisor import IngressObserverSupervisor


class FakeProcess:
    _next_pid = 4100

    def __init__(self, command: list[str], **kwargs) -> None:
        self.command = command
        self.kwargs = kwargs
        self.pid = FakeProcess._next_pid
        FakeProcess._next_pid += 1
        self.returncode = None
        self.terminated = False
        self.killed = False

    def poll(self):
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = 0

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9


def test_supervisor_autostarts_sensorlogger_mqtt_from_secret_env_file(tmp_path: Path) -> None:
    env_file = tmp_path / "sensorlogger-mqtt.env"
    env_file.write_text(
        "\n".join(
            [
                "VITE_MQTT_BROKER_URL=wss://cluster.example.test:8884/mqtt",
                "VITE_MQTT_USERNAME=demo-user",
                "VITE_MQTT_PASSWORD=demo-secret",
                "VITE_MQTT_TOPIC=scout/test/alex/sensorlogger",
            ]
        ),
        encoding="utf-8",
    )
    started: list[FakeProcess] = []

    def fake_popen(command, **kwargs):
        process = FakeProcess(list(command), **kwargs)
        started.append(process)
        return process

    supervisor = IngressObserverSupervisor.from_env(
        {
            "SCOUT_SENSORLOGGER_MQTT_ENV_FILE": str(env_file),
            "SCOUT_SENSORLOGGER_MQTT_EVIDENCE_DIR": str(tmp_path / "evidence"),
            "SCOUT_SENSORLOGGER_MQTT_LOG_PATH": str(tmp_path / "observer.log"),
        },
        app_root=tmp_path,
        popen_factory=fake_popen,
    )

    supervisor.start()
    status = supervisor.status()

    assert len(started) == 1
    command_text = " ".join(started[0].command)
    assert "scout_sensorlogger_mqtt_observer.py" in command_text
    assert "--env-file" in started[0].command
    assert str(env_file) in started[0].command
    assert "demo-secret" not in command_text
    assert status["enabled"] is True
    assert status["observer_count"] == 1
    assert status["running_count"] == 1
    assert status["observers"][0]["name"] == "sensorlogger-mqtt"
    assert status["observers"][0]["credential_value_exposed"] is False
    assert status["boundary"]["safety_api_called"] is False

    supervisor.stop()

    assert started[0].terminated is True


def test_supervisor_does_not_start_when_mqtt_is_not_configured(tmp_path: Path) -> None:
    started = []

    supervisor = IngressObserverSupervisor.from_env(
        {
            "SCOUT_SENSORLOGGER_MQTT_ENV_FILE": str(tmp_path / "missing.env"),
        },
        app_root=tmp_path,
        popen_factory=lambda command, **kwargs: started.append((command, kwargs)),
    )

    supervisor.start()
    status = supervisor.status()

    assert started == []
    assert status["observer_count"] == 0
    assert status["running_count"] == 0


def test_supervisor_autostarts_gnss_hardware_observer_from_jsonl_sources(tmp_path: Path) -> None:
    gateway_jsonl = tmp_path / "sx1303-gateway-gps.jsonl"
    grove_jsonl = tmp_path / "grove-gps.jsonl"
    gateway_jsonl.write_text("{}\n", encoding="utf-8")
    grove_jsonl.write_text("{}\n", encoding="utf-8")
    started: list[FakeProcess] = []

    def fake_popen(command, **kwargs):
        process = FakeProcess(list(command), **kwargs)
        started.append(process)
        return process

    supervisor = IngressObserverSupervisor.from_env(
        {
            "SCOUT_SENSORLOGGER_MQTT_AUTOSTART": "false",
            "SCOUT_GNSS_HARDWARE_AUTOSTART": "true",
            "SCOUT_GNSS_HARDWARE_GATEWAY_JSONL": str(gateway_jsonl),
            "SCOUT_GNSS_HARDWARE_GROVE_JSONL": str(grove_jsonl),
            "SCOUT_GNSS_HARDWARE_EVIDENCE_DIR": str(tmp_path / "gnss-evidence"),
            "SCOUT_GNSS_HARDWARE_LOG_PATH": str(tmp_path / "gnss-observer.log"),
            "SCOUT_GNSS_HARDWARE_POLL_SECONDS": "1.5",
            "SCOUT_GNSS_HARDWARE_MAX_RECORDS": "50",
        },
        app_root=tmp_path,
        popen_factory=fake_popen,
    )

    supervisor.start()
    status = supervisor.status()

    assert len(started) == 1
    command = started[0].command
    command_text = " ".join(command)
    assert "scout_gnss_hardware_observer.py" in command_text
    assert "--gateway-jsonl" in command
    assert str(gateway_jsonl) in command
    assert "--grove-jsonl" in command
    assert str(grove_jsonl) in command
    assert "--print-ready" in command
    assert "--poll-seconds" in command
    assert "1.5" in command
    assert "--max-records" in command
    assert "50" in command
    assert status["observer_count"] == 1
    assert status["running_count"] == 1
    assert status["configured_observer_names"] == ["gnss-hardware"]
    assert status["observers"][0]["name"] == "gnss-hardware"
    assert status["observers"][0]["reason"] == "configured_sources"
    assert status["observers"][0]["phase1_l0_l4_state_mutated"] is False
    assert status["observers"][0]["safety_api_called"] is False
    assert status["boundary"]["phase1_l0_l4_state_mutated"] is False

    supervisor.stop()

    assert started[0].terminated is True
