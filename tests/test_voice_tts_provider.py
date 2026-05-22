from __future__ import annotations

import subprocess

from voice_tts_provider import (
    EspeakNGFallbackProvider,
    PiperTTSProvider,
    configured_provider_for_engine,
    execute_command_plan,
    provider_for_engine,
)


def test_piper_provider_builds_command_plan_without_requiring_binary() -> None:
    provider = PiperTTSProvider(model_path="/models/zh.onnx")

    plan = provider.command_plan(text_zh="請停下確認方向。", audio_file="/tmp/scout.wav")

    assert plan.engine == "piper"
    assert plan.render_command == [
        "piper",
        "--model",
        "/models/zh.onnx",
        "--output_file",
        "/tmp/scout.wav",
    ]
    assert plan.stdin_text == "請停下確認方向。"
    assert plan.playback_command == ["aplay", "/tmp/scout.wav"]
    assert plan.boundary.safety_decision_change_allowed is False
    assert plan.boundary.remote_outbound_allowed is False
    assert plan.boundary.hardware_control_allowed is False


def test_espeak_fallback_provider_builds_command_plan() -> None:
    provider = EspeakNGFallbackProvider(voice="zh")

    plan = provider.command_plan(text_zh="裝置電量偏低。", audio_file="/tmp/scout.wav")

    assert plan.engine == "espeak"
    assert plan.render_command == [
        "espeak-ng",
        "-v",
        "zh",
        "-w",
        "/tmp/scout.wav",
        "裝置電量偏低。",
    ]
    assert plan.stdin_text is None
    assert plan.playback_command == ["aplay", "/tmp/scout.wav"]


def test_provider_for_engine_defaults_to_piper_and_fallback() -> None:
    assert provider_for_engine("piper").engine == "piper"
    assert provider_for_engine("espeak").engine == "espeak"


def test_configured_provider_for_engine_allows_local_playback_command() -> None:
    provider = configured_provider_for_engine(
        "piper",
        piper_binary="venv/bin/piper",
        piper_model_path="/tmp/model.onnx",
        playback_binary="afplay",
    )

    plan = provider.command_plan(text_zh="本機播放測試。", audio_file="/tmp/scout.wav")

    assert plan.render_command[0] == "venv/bin/piper"
    assert plan.render_command[2] == "/tmp/model.onnx"
    assert plan.playback_command == ["afplay", "/tmp/scout.wav"]


def test_configured_provider_for_engine_allows_playback_command_with_args() -> None:
    provider = configured_provider_for_engine(
        "piper",
        piper_binary="venv/bin/piper",
        piper_model_path="/tmp/model.onnx",
        playback_binary=[
            "aplay",
            "-D",
            "bluealsa:DEV=34:D2:CF:30:6F:2C,PROFILE=a2dp,SRV=org.bluealsa",
        ],
    )

    plan = provider.command_plan(text_zh="藍牙播放測試。", audio_file="/tmp/scout.wav")

    assert plan.playback_command == [
        "aplay",
        "-D",
        "bluealsa:DEV=34:D2:CF:30:6F:2C,PROFILE=a2dp,SRV=org.bluealsa",
        "/tmp/scout.wav",
    ]


def test_execute_command_plan_uses_injected_runner() -> None:
    plan = PiperTTSProvider(model_path="/models/zh.onnx").command_plan(
        text_zh="測試語音。",
        audio_file="/tmp/scout.wav",
    )
    calls: list[dict[str, object]] = []

    def fake_runner(command, **kwargs):
        calls.append({"command": command, **kwargs})
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    results = execute_command_plan(plan, runner=fake_runner)

    assert len(results) == 2
    assert calls[0]["command"] == plan.render_command
    assert calls[0]["input"] == "測試語音。"
    assert calls[1]["command"] == plan.playback_command
