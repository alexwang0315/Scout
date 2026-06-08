from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable, Literal, Protocol, Sequence

from pydantic import BaseModel, ConfigDict, Field

from voice_cue_models import VoiceCueBoundary


TTSEngine = Literal["piper", "espeak"]


class TTSCommandPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    engine: TTSEngine
    text_zh: str = Field(min_length=1)
    audio_file: str = Field(min_length=1)
    render_command: list[str] = Field(min_length=1)
    playback_command: list[str] = Field(min_length=1)
    stdin_text: str | None = None
    boundary: VoiceCueBoundary = Field(default_factory=VoiceCueBoundary)


class TTSProvider(Protocol):
    engine: TTSEngine

    def command_plan(self, *, text_zh: str, audio_file: Path | str) -> TTSCommandPlan:
        ...


class PiperTTSProvider:
    engine: Literal["piper"] = "piper"

    def __init__(
        self,
        *,
        piper_binary: str = "piper",
        model_path: Path | str = "/data/scout/providers/voice_cue/piper/default.onnx",
        playback_command: str | Sequence[str] = "aplay",
    ):
        self.piper_binary = piper_binary
        self.model_path = str(model_path)
        self.playback_command = _command_prefix(playback_command)

    def command_plan(self, *, text_zh: str, audio_file: Path | str) -> TTSCommandPlan:
        return TTSCommandPlan(
            engine=self.engine,
            text_zh=text_zh,
            audio_file=str(audio_file),
            render_command=[
                self.piper_binary,
                "--model",
                self.model_path,
                "--output_file",
                str(audio_file),
            ],
            playback_command=[*self.playback_command, str(audio_file)],
            stdin_text=text_zh,
        )


class EspeakNGFallbackProvider:
    engine: Literal["espeak"] = "espeak"

    def __init__(
        self,
        *,
        espeak_binary: str = "espeak-ng",
        voice: str = "zh",
        playback_command: str | Sequence[str] = "aplay",
    ):
        self.espeak_binary = espeak_binary
        self.voice = voice
        self.playback_command = _command_prefix(playback_command)

    def command_plan(self, *, text_zh: str, audio_file: Path | str) -> TTSCommandPlan:
        return TTSCommandPlan(
            engine=self.engine,
            text_zh=text_zh,
            audio_file=str(audio_file),
            render_command=[
                self.espeak_binary,
                "-v",
                self.voice,
                "-w",
                str(audio_file),
                text_zh,
            ],
            playback_command=[*self.playback_command, str(audio_file)],
        )


def provider_for_engine(engine: TTSEngine) -> TTSProvider:
    if engine == "piper":
        return PiperTTSProvider()
    return EspeakNGFallbackProvider()


def configured_provider_for_engine(
    engine: TTSEngine,
    *,
    piper_binary: str = "piper",
    piper_model_path: Path | str = "/data/scout/providers/voice_cue/piper/default.onnx",
    espeak_binary: str = "espeak-ng",
    espeak_voice: str = "zh",
    playback_binary: str = "aplay",
) -> TTSProvider:
    if engine == "piper":
        return PiperTTSProvider(
            piper_binary=piper_binary,
            model_path=piper_model_path,
            playback_command=playback_binary,
        )
    return EspeakNGFallbackProvider(
        espeak_binary=espeak_binary,
        voice=espeak_voice,
        playback_command=playback_binary,
    )


SubprocessRunner = Callable[..., subprocess.CompletedProcess[str]]


def execute_command_plan(
    plan: TTSCommandPlan,
    *,
    runner: SubprocessRunner = subprocess.run,
) -> list[subprocess.CompletedProcess[str]]:
    render_result = _run(
        runner,
        plan.render_command,
        input_text=plan.stdin_text,
    )
    playback_result = _run(runner, plan.playback_command)
    return [render_result, playback_result]


def _run(
    runner: SubprocessRunner,
    command: Sequence[str],
    *,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    return runner(
        list(command),
        check=True,
        input=input_text,
        text=True,
        capture_output=True,
    )


def _command_prefix(command: str | Sequence[str]) -> list[str]:
    if isinstance(command, str):
        return [command]
    return list(command)
