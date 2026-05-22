from __future__ import annotations

import argparse
import json
import shlex
import sys
from subprocess import CalledProcessError
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from voice_tts_provider import configured_provider_for_engine, execute_command_plan


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Render a local Scout voice cue TTS command plan for Pi smoke testing."
    )
    parser.add_argument("text_zh", help="Chinese text to render as a local voice cue.")
    parser.add_argument("--engine", choices=("piper", "espeak"), default="piper")
    parser.add_argument("--piper-binary", default="piper")
    parser.add_argument(
        "--piper-model",
        type=Path,
        default=Path("/data/scout/providers/voice_cue/piper/default.onnx"),
    )
    parser.add_argument("--espeak-binary", default="espeak-ng")
    parser.add_argument("--espeak-voice", default="zh")
    parser.add_argument("--playback-command", default="aplay")
    parser.add_argument(
        "--audio-file",
        type=Path,
        default=Path("/data/scout/providers/voice_cue/manual-smoke.wav"),
    )
    parser.add_argument("--output-jsonl", type=Path)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()

    provider = configured_provider_for_engine(
        args.engine,
        piper_binary=args.piper_binary,
        piper_model_path=args.piper_model,
        espeak_binary=args.espeak_binary,
        espeak_voice=args.espeak_voice,
        playback_binary=shlex.split(args.playback_command),
    )
    plan = provider.command_plan(text_zh=args.text_zh, audio_file=args.audio_file)
    payload = {
        "source": "pi_voice_tts_smoke",
        "smoke_kind": "voice_tts_command_plan",
        "created_at": _utc_now(),
        "mode": "execute" if args.execute else "dry_run",
        "command_plan": plan.model_dump(mode="json"),
        "boundary": plan.boundary.model_dump(mode="json"),
        "safety_decision_change_allowed": False,
        "remote_outbound_allowed": False,
        "hardware_control_allowed": False,
    }

    exit_code = 0
    if args.execute:
        try:
            execute_command_plan(plan)
            payload["executed"] = True
            payload["execution_failed"] = False
        except CalledProcessError as exc:
            payload["executed"] = False
            payload["execution_failed"] = True
            payload["error_type"] = type(exc).__name__
            payload["error_message"] = str(exc)
            payload["failed_command"] = list(exc.cmd) if isinstance(exc.cmd, list) else exc.cmd
            payload["returncode"] = exc.returncode
            payload["stdout"] = exc.stdout
            payload["stderr"] = exc.stderr
            exit_code = exc.returncode or 1
    else:
        payload["executed"] = False
        payload["execution_failed"] = False

    if args.output_jsonl is not None:
        args.output_jsonl.parent.mkdir(parents=True, exist_ok=True)
        with args.output_jsonl.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return exit_code


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    raise SystemExit(main())
