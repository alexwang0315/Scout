from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "voice_cue" / "demo_cues.json"


def _load_tool_module(name: str, relative_path: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_voice_cue_debug_demo_selects_warning_and_writes_jsonl(tmp_path) -> None:
    module = _load_tool_module("voice_cue_debug_demo_test", "tools/voice_cue_debug_demo.py")
    transport_jsonl = tmp_path / "voice-transport.jsonl"
    debug_jsonl = tmp_path / "voice-debug.jsonl"

    result = module.run_voice_cue_debug_demo(
        cue_fixture=FIXTURE,
        engine="piper",
        audio_file=tmp_path / "voice.wav",
        transport_jsonl=transport_jsonl,
        debug_jsonl=debug_jsonl,
        session_id="debug_session.voice.test",
        mission_id="mission.normal_climb",
        now="2026-05-21T10:00:00Z",
    )

    assert result["mode"] == "dry_run"
    assert result["executed"] is False
    assert result["selected_cue_id"] == "voice_cue.route.000001"
    assert result["command_plan"]["engine"] == "piper"
    assert result["transport_record_count"] == 1
    assert result["debug_event_count"] == 2
    assert result["debug_event_kinds"] == ["voice_cue_queued", "voice_cue_state_changed"]
    assert result["boundary"]["safety_decision_change_allowed"] is False
    assert result["boundary"]["remote_outbound_allowed"] is False
    assert result["boundary"]["hardware_control_allowed"] is False

    transport_lines = [
        json.loads(line) for line in transport_jsonl.read_text(encoding="utf-8").splitlines()
    ]
    debug_lines = [
        json.loads(line) for line in debug_jsonl.read_text(encoding="utf-8").splitlines()
    ]
    assert [line["state"] for line in transport_lines] == ["queued", "rendered"]
    assert [line["kind"] for line in debug_lines] == ["voice_cue_queued", "voice_cue_state_changed"]
    assert all(line["payload"]["boundary"]["remote_outbound_allowed"] is False for line in debug_lines)


def test_voice_cue_debug_demo_cli_outputs_espeak_plan_without_tts_installation(tmp_path) -> None:
    transport_jsonl = tmp_path / "voice-transport.jsonl"
    debug_jsonl = tmp_path / "voice-debug.jsonl"
    completed = subprocess.run(
        [
            sys.executable,
            "tools/voice_cue_debug_demo.py",
            "--cue-fixture",
            str(FIXTURE),
            "--engine",
            "espeak",
            "--audio-file",
            str(tmp_path / "voice.wav"),
            "--transport-jsonl",
            str(transport_jsonl),
            "--debug-jsonl",
            str(debug_jsonl),
            "--now",
            "2026-05-21T10:00:00Z",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(completed.stdout)
    assert payload["selected_cue_id"] == "voice_cue.route.000001"
    assert payload["command_plan"]["engine"] == "espeak"
    assert payload["command_plan"]["render_command"][0] == "espeak-ng"
    assert payload["remote_outbound_allowed"] is False
    assert payload["hardware_control_allowed"] is False
    assert len(transport_jsonl.read_text(encoding="utf-8").splitlines()) == 2
    assert len(debug_jsonl.read_text(encoding="utf-8").splitlines()) == 2


def test_voice_cue_debug_demo_source_has_no_live_runtime_or_transport_calls() -> None:
    source = (ROOT / "tools" / "voice_cue_debug_demo.py").read_text(encoding="utf-8")

    for forbidden in (
        "execute_command_plan",
        "subprocess",
        "requests",
        "httpx",
        "urllib",
        "safety_api",
        "/safety/",
        "mock_outbound_transport",
        "bluetooth",
    ):
        assert forbidden not in source
