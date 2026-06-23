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


def test_supervisor_passes_gnss_hardware_oled_and_led_options(tmp_path: Path) -> None:
    gateway_jsonl = tmp_path / "sx1303-gateway-gps.jsonl"
    gateway_jsonl.write_text("{}\n", encoding="utf-8")
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
            "SCOUT_GNSS_HARDWARE_GROVE_JSONL": str(tmp_path / "missing-grove.jsonl"),
            "SCOUT_GNSS_HARDWARE_EVIDENCE_DIR": str(tmp_path / "gnss-evidence"),
            "SCOUT_GNSS_HARDWARE_LOG_PATH": str(tmp_path / "gnss-observer.log"),
            "SCOUT_GNSS_HARDWARE_OLED_STATUS": "true",
            "SCOUT_GNSS_HARDWARE_OLED_DRIVER": "sh1107g",
            "SCOUT_GNSS_HARDWARE_LED_STATUS": "true",
            "SCOUT_GNSS_HARDWARE_LED_PORT": "D5",
            "SCOUT_GNSS_HARDWARE_LED_FIX_BIT": "10",
            "SCOUT_GNSS_HARDWARE_LED_NO_FIX_BIT": "1",
            "SCOUT_GNSS_HARDWARE_LED_BLINK_COUNT": "1",
            "SCOUT_GNSS_HARDWARE_LED_BLINK_SECONDS": "0.15",
        },
        app_root=tmp_path,
        popen_factory=fake_popen,
    )

    supervisor.start()
    command = started[0].command

    assert "--oled-status" in command
    assert "--oled-driver" in command
    assert "sh1107g" in command
    assert "--led-status" in command
    assert "--led-port" in command
    assert "D5" in command
    assert "--led-fix-bit" in command
    assert "10" in command
    assert "--led-no-fix-bit" in command
    assert "1" in command
    assert "--led-blink-seconds" in command
    assert "0.15" in command
    assert "/safety/" not in " ".join(command)

    supervisor.stop()


def test_supervisor_autostarts_physiologic_gate_observer_when_explicit(tmp_path: Path) -> None:
    vitals_jsonl = tmp_path / "sensorlogger_mqtt_sensor_vitals_records.jsonl"
    baseline_json = tmp_path / "baseline.json"
    route_context_json = tmp_path / "route-context.json"
    vitals_jsonl.write_text("{}\n", encoding="utf-8")
    baseline_json.write_text('{"personal_envelope_available": false}\n', encoding="utf-8")
    route_context_json.write_text(
        "\n".join(
            [
                "{",
                '  "route_id": "fixture.route",',
                '  "segment_id": "fixture.segment",',
                '  "distance_to_next_checkpoint_m": 500,',
                '  "estimated_minutes_to_next_checkpoint": 25,',
                '  "estimated_minutes_to_planned_camp": 90,',
                '  "daylight_buffer_minutes": 80',
                "}",
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
            "SCOUT_SENSORLOGGER_MQTT_AUTOSTART": "false",
            "SCOUT_GNSS_HARDWARE_AUTOSTART": "false",
            "SCOUT_PHYSIOLOGIC_GATE_AUTOSTART": "true",
            "SCOUT_PHYSIOLOGIC_GATE_SENSORLOGGER_VITALS_JSONL": str(vitals_jsonl),
            "SCOUT_PHYSIOLOGIC_GATE_BASELINE_JSON": str(baseline_json),
            "SCOUT_PHYSIOLOGIC_GATE_ROUTE_CONTEXT_JSON": str(route_context_json),
            "SCOUT_PHYSIOLOGIC_GATE_EVIDENCE_DIR": str(tmp_path / "physio-evidence"),
            "SCOUT_PHYSIOLOGIC_GATE_LOG_PATH": str(tmp_path / "physio-observer.log"),
            "SCOUT_PHYSIOLOGIC_GATE_POLL_SECONDS": "5",
            "SCOUT_PHYSIOLOGIC_GATE_WINDOW_MINUTES": "15",
        },
        app_root=tmp_path,
        popen_factory=fake_popen,
    )

    supervisor.start()
    status = supervisor.status()
    command = started[0].command
    command_text = " ".join(command)

    assert len(started) == 1
    assert "scout_physiologic_gate_observer.py" in command_text
    assert "--sensorlogger-vitals-jsonl" in command
    assert str(vitals_jsonl) in command
    assert "--baseline-json" in command
    assert str(baseline_json) in command
    assert "--route-context-json" in command
    assert str(route_context_json) in command
    assert "--window-minutes" in command
    assert "15" in command
    assert "/safety/" not in command_text
    assert status["observer_count"] == 1
    assert status["running_count"] == 1
    assert status["configured_observer_names"] == ["physiologic-gate"]
    assert status["observers"][0]["name"] == "physiologic-gate"
    assert status["observers"][0]["reason"] == "explicit_autostart"
    assert status["observers"][0]["phase1_l0_l4_state_mutated"] is False
    assert status["observers"][0]["safety_api_called"] is False
    assert status["boundary"]["phase1_l0_l4_state_mutated"] is False

    supervisor.stop()

    assert started[0].terminated is True
