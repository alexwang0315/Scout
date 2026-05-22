from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load_tool_module(name: str, relative_path: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_pi_voice_tts_smoke_dry_run_outputs_piper_plan_and_jsonl(tmp_path, monkeypatch, capsys) -> None:
    module = _load_tool_module("pi_voice_tts_smoke_test", "tools/pi_voice_tts_smoke.py")
    output_path = tmp_path / "manual-smoke.jsonl"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "pi_voice_tts_smoke.py",
            "請停下確認方向。",
            "--engine",
            "piper",
            "--piper-binary",
            "venv/bin/piper",
            "--piper-model",
            "/tmp/model.onnx",
            "--playback-command",
            "aplay -D bluealsa:DEV=34:D2:CF:30:6F:2C,PROFILE=a2dp,SRV=org.bluealsa",
            "--audio-file",
            str(tmp_path / "voice.wav"),
            "--output-jsonl",
            str(output_path),
        ],
    )

    assert module.main() == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["mode"] == "dry_run"
    assert payload["executed"] is False
    assert payload["command_plan"]["engine"] == "piper"
    assert payload["command_plan"]["render_command"][0] == "venv/bin/piper"
    assert payload["command_plan"]["render_command"][2] == "/tmp/model.onnx"
    assert payload["command_plan"]["playback_command"][:3] == [
        "aplay",
        "-D",
        "bluealsa:DEV=34:D2:CF:30:6F:2C,PROFILE=a2dp,SRV=org.bluealsa",
    ]
    assert payload["command_plan"]["stdin_text"] == "請停下確認方向。"
    assert payload["boundary"]["safety_decision_change_allowed"] is False
    assert payload["boundary"]["remote_outbound_allowed"] is False
    assert payload["boundary"]["hardware_control_allowed"] is False

    lines = output_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["command_plan"]["engine"] == "piper"


def test_pi_voice_tts_smoke_can_render_espeak_dry_run_without_installation(tmp_path) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "tools/pi_voice_tts_smoke.py",
            "裝置電量偏低。",
            "--engine",
            "espeak",
            "--audio-file",
            str(tmp_path / "voice.wav"),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(completed.stdout)
    assert payload["mode"] == "dry_run"
    assert payload["executed"] is False
    assert payload["command_plan"]["engine"] == "espeak"
    assert payload["command_plan"]["render_command"][0] == "espeak-ng"
    assert payload["remote_outbound_allowed"] is False


def test_pi_voice_tts_smoke_records_execute_failure_jsonl(tmp_path, monkeypatch, capsys) -> None:
    module = _load_tool_module("pi_voice_tts_smoke_failure_test", "tools/pi_voice_tts_smoke.py")
    output_path = tmp_path / "manual-smoke.jsonl"

    def fake_execute(plan):
        raise subprocess.CalledProcessError(
            1,
            ["aplay", plan.audio_file],
            output="",
            stderr="audio open error: Unknown error 524",
        )

    monkeypatch.setattr(module, "execute_command_plan", fake_execute)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "pi_voice_tts_smoke.py",
            "請停下確認方向。",
            "--engine",
            "piper",
            "--audio-file",
            str(tmp_path / "voice.wav"),
            "--output-jsonl",
            str(output_path),
            "--execute",
        ],
    )

    assert module.main() == 1

    payload = json.loads(capsys.readouterr().out)
    assert payload["executed"] is False
    assert payload["execution_failed"] is True
    assert payload["error_type"] == "CalledProcessError"
    assert payload["returncode"] == 1
    assert payload["stderr"] == "audio open error: Unknown error 524"
    assert json.loads(output_path.read_text(encoding="utf-8"))["execution_failed"] is True
