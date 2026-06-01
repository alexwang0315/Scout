from __future__ import annotations

import json
from pathlib import Path

from assistant_model_config import AssistantModelConfig
from tools import pi_scout_agent_keypad_pydantic_ai as keypad_agent


REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_DIR = REPO_ROOT / "tools" / "scout_agent_tool_manifests"


class PromptAwareRunner:
    def __init__(self, *, wrong_tool: bool = False) -> None:
        self.wrong_tool = wrong_tool
        self.calls: list[dict[str, object]] = []

    def run(self, prompt: str, *, timeout_seconds: int) -> str:
        self.calls.append({"prompt": prompt, "timeout_seconds": timeout_seconds})
        payload = json.loads(prompt)
        context = payload["context"]
        tool_id = "scout.voice.preview" if self.wrong_tool else context["expected_tool_id"]
        return json.dumps(
            {
                "artifact_kind": "scout_agent_tool_plan",
                "plan_id": "agent_plan.hardware_keypad_test.001",
                "agent_run_id": "agent_run.hardware_keypad_test.001",
                "user_intent": payload["user_intent"],
                "tool_calls": [
                    {
                        "tool_id": tool_id,
                        "action_id": "agent_action.hardware_keypad_test.001",
                        "input_path": context["required_input_path"],
                        "output_path": context["required_output_path"],
                        "dry_run": True,
                        "authorized_by": "operator.hardware_keypad_lab",
                    }
                ],
            }
        )


def test_keypad_pydantic_ai_runner_executes_safe_tool_with_oled_and_voice_dry_run(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    runner = PromptAwareRunner()

    summary = keypad_agent.run_keypad_pydantic_ai_bridge(
        rows=[16, 17, 18, 19],
        cols=[24, 25, 26, 27],
        grove_ports=["D16", "D18", "D24", "D26"],
        active_low=False,
        duration_seconds=0.0,
        poll_interval_ms=25.0,
        debounce_ms=120.0,
        dry_run=True,
        simulated_keys=["S1"],
        assistant_config_path=config_path,
        manifest_dir=MANIFEST_DIR,
        output_dir=tmp_path / "run",
        output_jsonl=tmp_path / "run" / "events.jsonl",
        trace_log_path=tmp_path / "run" / "trace.jsonl",
        inherit_runtime_env_from_pid=None,
        local_model_base_url_override="http://127.0.0.1:11434/v1",
        timeout_seconds=4,
        oled_options=_oled_options(),
        voice_options=_voice_options(tmp_path),
        runner_factory=lambda _profile: runner,
    )

    assert summary["status"] == "completed"
    assert summary["provider_status"]["runner_profile"] == "cloud"
    assert summary["key_runs"][0]["expected_tool_id"] == "scout.local_evidence.status"
    assert summary["key_runs"][0]["execution"]["status"] == "completed"
    assert summary["key_runs"][0]["live_safety_api_called"] is False
    assert {event["stage"] for event in summary["feedback_events"]} >= {
        "ready",
        "key_captured",
        "model_planning",
        "plan_ok",
        "tool_run",
        "done",
    }
    assert all(event["oled"]["write_status"] == "dry_run" for event in summary["feedback_events"])
    assert all(event["voice"]["write_status"] == "dry_run" for event in summary["feedback_events"])
    assert all(event["voice"]["command_plan"]["engine"] == "piper" for event in summary["feedback_events"])
    assert "SCOUT_CLOUD_MODEL_TOKEN" in summary["provider_status"]["token_env_refs"]
    assert "secret" not in json.dumps(summary, ensure_ascii=False)
    assert (tmp_path / "run" / "trace.jsonl").exists()


def test_keypad_pydantic_ai_runner_rejects_unexpected_model_tool(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    runner = PromptAwareRunner(wrong_tool=True)

    summary = keypad_agent.run_keypad_pydantic_ai_bridge(
        rows=[16, 17, 18, 19],
        cols=[24, 25, 26, 27],
        grove_ports=["D16", "D18", "D24", "D26"],
        active_low=False,
        duration_seconds=0.0,
        poll_interval_ms=25.0,
        debounce_ms=120.0,
        dry_run=True,
        simulated_keys=["S1"],
        assistant_config_path=config_path,
        manifest_dir=MANIFEST_DIR,
        output_dir=tmp_path / "run",
        output_jsonl=None,
        trace_log_path=tmp_path / "run" / "trace.jsonl",
        inherit_runtime_env_from_pid=None,
        local_model_base_url_override=None,
        timeout_seconds=4,
        oled_options=_oled_options(),
        voice_options=_voice_options(tmp_path),
        runner_factory=lambda _profile: runner,
    )

    assert summary["status"] == "failed"
    assert summary["key_runs"][0]["status"] == "model_plan_rejected"
    assert "unexpected tool_id" in summary["key_runs"][0]["error"]
    assert not (tmp_path / "run" / "trace.jsonl").exists()
    assert "model_plan_rejected" in {event["stage"] for event in summary["feedback_events"]}


def test_parse_environ_bytes_keeps_only_key_value_entries() -> None:
    parsed = keypad_agent.parse_environ_bytes(
        b"SCOUT_CLOUD_MODEL_TOKEN=secret-token\x00NO_EQUALS\x00OPENAI_BASE_URL=http://example\x00"
    )

    assert parsed == {
        "SCOUT_CLOUD_MODEL_TOKEN": "secret-token",
        "OPENAI_BASE_URL": "http://example",
    }


def _write_config(tmp_path: Path) -> Path:
    config = AssistantModelConfig.model_validate(
        {
            "active_profile": "cloud",
            "cloud_model": {
                "profile": "cloud",
                "model_name": "google/gemma-3-27b-it",
                "base_url": "https://openrouter.ai/api/v1",
                "token_env_var": "SCOUT_CLOUD_MODEL_TOKEN",
                "token_id": "operator-managed-openrouter-token",
            },
            "local_model": {
                "profile": "local",
                "model_name": "qwen2.5:0.5b",
                "base_url": "http://127.0.0.1:11434/v1",
                "token_id": "ollama-local-no-token",
            },
            "timeout_seconds": 4,
            "fallback_to_local_on_error": True,
            "local_fallback_fixed_schema": True,
        }
    )
    path = tmp_path / "assistant-models.json"
    path.write_text(config.model_dump_json(indent=2), encoding="utf-8")
    return path


def _oled_options() -> dict[str, object]:
    return {
        "enabled": True,
        "dry_run": True,
        "bus": Path("/dev/i2c-1"),
        "address": 0x3C,
        "driver": "sh1107g",
    }


def _voice_options(tmp_path: Path) -> dict[str, object]:
    return {
        "enabled": True,
        "execute": False,
        "engine": "piper",
        "piper_binary": "/tmp/piper",
        "piper_model": tmp_path / "voice.onnx",
        "espeak_binary": "espeak-ng",
        "espeak_voice": "zh",
        "playback_command": "aplay",
        "audio_dir": tmp_path / "voice",
    }
