from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mock_voice_transport import MockVoiceTransport
from runtime_debug_log import FileRuntimeDebugEventLog, MemoryRuntimeDebugEventLog
from voice_cue_models import VoiceCue, VoiceCueBoundary
from voice_cue_policy import VoiceCuePolicy
from voice_tts_provider import provider_for_engine


DEFAULT_CUE_FIXTURE = (
    Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "voice_cue" / "demo_cues.json"
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Dry-run a fixture-backed Scout voice cue debug pipeline."
    )
    parser.add_argument("--cue-fixture", type=Path, default=DEFAULT_CUE_FIXTURE)
    parser.add_argument("--engine", choices=("piper", "espeak"), default="piper")
    parser.add_argument(
        "--audio-file",
        type=Path,
        default=Path("/data/scout/providers/voice_cue/debug-demo.wav"),
    )
    parser.add_argument("--transport-jsonl", type=Path)
    parser.add_argument("--debug-jsonl", type=Path)
    parser.add_argument("--session-id", default="debug_session.voice_cue_demo")
    parser.add_argument("--mission-id", default="mission.voice_cue_demo")
    parser.add_argument("--now", default=None, help="ISO-8601 timestamp for deterministic dry-runs.")
    args = parser.parse_args()

    result = run_voice_cue_debug_demo(
        cue_fixture=args.cue_fixture,
        engine=args.engine,
        audio_file=args.audio_file,
        transport_jsonl=args.transport_jsonl,
        debug_jsonl=args.debug_jsonl,
        session_id=args.session_id,
        mission_id=args.mission_id,
        now=args.now,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def run_voice_cue_debug_demo(
    *,
    cue_fixture: Path,
    engine: str,
    audio_file: Path,
    transport_jsonl: Path | None = None,
    debug_jsonl: Path | None = None,
    session_id: str = "debug_session.voice_cue_demo",
    mission_id: str = "mission.voice_cue_demo",
    now: str | None = None,
) -> dict[str, Any]:
    timestamp = now or _utc_now()
    cues = load_voice_cues(cue_fixture)
    policy = VoiceCuePolicy()
    decision = policy.choose_next(cues, now=_parse_iso(timestamp))
    debug_log = (
        FileRuntimeDebugEventLog(debug_jsonl)
        if debug_jsonl is not None
        else MemoryRuntimeDebugEventLog()
    )
    transport = MockVoiceTransport(
        output_jsonl=transport_jsonl,
        debug_log=debug_log,
        session_id=session_id,
        mission_id=mission_id,
        timestamp_factory=lambda: timestamp,
    )

    command_plan = None
    selected_record = None
    if decision.selected is not None:
        provider = provider_for_engine(engine)  # type: ignore[arg-type]
        command_plan = provider.command_plan(
            text_zh=decision.selected.text_zh,
            audio_file=audio_file,
        )
        transport.queue_voice_cue(
            decision.selected,
            engine=command_plan.engine,
            audio_file=command_plan.audio_file,
        )
        selected_record = transport.mark_rendered(
            decision.selected.cue_id,
            engine=command_plan.engine,
            audio_file=command_plan.audio_file,
        )

    events = debug_log.list_events()
    boundary = VoiceCueBoundary().model_dump(mode="json")
    return {
        "source": "voice_cue_debug_demo",
        "mode": "dry_run",
        "executed": False,
        "cue_fixture": str(cue_fixture),
        "engine": engine,
        "selected_cue_id": decision.selected.cue_id if decision.selected else None,
        "selected_record": (
            selected_record.model_dump(mode="json") if selected_record is not None else None
        ),
        "suppressed": [
            {"cue_id": item.cue_id, "reason": item.reason} for item in decision.suppressed
        ],
        "command_plan": command_plan.model_dump(mode="json") if command_plan else None,
        "transport_record_count": len(transport.list_records()),
        "debug_event_count": len(events),
        "debug_event_kinds": [event.kind for event in events],
        "boundary": boundary,
        "safety_decision_change_allowed": False,
        "remote_outbound_allowed": False,
        "hardware_control_allowed": False,
    }


def load_voice_cues(path: Path) -> list[VoiceCue]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("voice cue fixture must be a JSON list")
    return [VoiceCue.model_validate(item) for item in payload]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_iso(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


if __name__ == "__main__":
    raise SystemExit(main())
