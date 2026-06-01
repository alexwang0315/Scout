from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from subprocess import CalledProcessError
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from assistant_model_config import AssistantModelConfig, load_assistant_model_config
from scout_agent_runtime import (
    ScoutAgentPlannerRunner,
    ScoutAgentToolPlan,
    build_agent_tool_planning_prompt,
    build_scout_agent_planner_provider_status,
    create_configured_scout_agent_planner_runner,
    parse_agent_tool_plan,
    run_agent_tool_plan,
)
from scout_agent_tools import find_tool_manifest
from tools.pi_keypad_4x4_smoke import (
    DEFAULT_GROVE_PORTS,
    PHYSICAL_LABEL_LAYOUT,
    build_summary as build_keypad_summary,
    parse_grove_ports,
    parse_gpio_list,
    parse_non_negative_float,
    parse_positive_float,
    parse_simulated_keys,
    rows_cols_from_grove_ports,
    scan_keypad_events,
)
from tools.pi_oled_i2c_smoke import parse_address, write_display
from voice_tts_provider import configured_provider_for_engine, execute_command_plan


SOURCE = "pi_scout_agent_keypad_pydantic_ai"
HARDWARE_KIND = "matrix_keypad_4x4_pydantic_ai_agent_trigger"
DEFAULT_MANIFEST_DIR = Path(__file__).resolve().parent / "scout_agent_tool_manifests"
DEFAULT_ASSISTANT_CONFIG = Path("/data/scout/config/assistant-models.json")
DEFAULT_OUTPUT_DIR = Path("/tmp/scout-agent-keypad-pydantic-ai")
DEFAULT_PIPER_BINARY = "/home/alexwang0315/scout-voice-cue-smoke/venv/bin/piper"
DEFAULT_PIPER_MODEL = Path(
    "/data/scout/providers/voice_cue/piper/zh_CN-huayan-medium/zh_CN-huayan-medium.onnx"
)
DEFAULT_PLAYBACK_COMMAND = "aplay -D bluealsa:DEV=34:D2:CF:30:6F:2C,PROFILE=a2dp,SRV=org.bluealsa"
INHERITABLE_ENV_KEYS = (
    "SCOUT_AI_ASSISTANT_CONFIG_PATH",
    "SCOUT_AI_ASSISTANT_PROVIDER",
    "SCOUT_AI_ASSISTANT_ENABLED",
    "SCOUT_CLOUD_MODEL_TOKEN",
    "OPENROUTER_API_KEY",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "OLLAMA_HOST",
)


KEY_TOOL_ACTIONS = {
    "S1": {
        "expected_tool_id": "scout.local_evidence.status",
        "voice_label_zh": "本地證據狀態",
        "input": {
            "trip_id": "hardware_agent_keypad_test",
            "source": SOURCE,
            "operator_triggered": True,
        },
    },
    "S2": {
        "expected_tool_id": "scout.kb.hardware_readiness_summary",
        "voice_label_zh": "硬體 readiness 摘要",
        "input": {
            "selected_provider_ref": "hardware_keypad_pydantic_ai_test",
            "source": SOURCE,
            "operator_triggered": True,
        },
    },
    "S3": {
        "expected_tool_id": "scout.debug.trace_tail",
        "voice_label_zh": "agent trace tail",
        "input": {
            "trace_kind": "agent_tool",
            "limit": 5,
            "source": SOURCE,
            "operator_triggered": True,
        },
    },
    "S4": {
        "expected_tool_id": "scout.voice.preview",
        "voice_label_zh": "語音 preview",
        "input": {
            "text_zh": "Scout agent hardware key test. Pydantic AI 已建立語音預覽計畫。",
            "engine": "piper",
            "audio_file": "/tmp/scout-agent-keypad-pydantic-ai/voice-preview.wav",
            "source": SOURCE,
            "operator_triggered": True,
        },
    },
}


RunnerFactory = Callable[[Any], ScoutAgentPlannerRunner]
VoiceExecutor = Callable[..., list[Any]]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_environ_bytes(payload: bytes) -> dict[str, str]:
    env: dict[str, str] = {}
    for raw_item in payload.split(b"\x00"):
        if not raw_item or b"=" not in raw_item:
            continue
        raw_key, raw_value = raw_item.split(b"=", 1)
        key = raw_key.decode("utf-8", errors="replace")
        value = raw_value.decode("utf-8", errors="replace")
        env[key] = value
    return env


def inherit_runtime_environment(
    mode: str | None,
    *,
    base_environ: dict[str, str] | None = None,
) -> tuple[dict[str, str], dict[str, Any]]:
    env = dict(base_environ or os.environ)
    meta = {
        "mode": mode or "disabled",
        "selected_pid": None,
        "inherited_env_keys": [],
        "token_env_present": bool(env.get("SCOUT_CLOUD_MODEL_TOKEN")),
        "errors": [],
    }
    if not mode or mode == "disabled":
        return env, meta
    if not Path("/proc").exists():
        meta["errors"].append("/proc not available")
        return env, meta

    candidates = _runtime_env_candidates(mode)
    if not candidates:
        meta["errors"].append("no matching runtime process environ found")
        return env, meta
    selected_pid, inherited = candidates[0]
    meta["selected_pid"] = selected_pid
    for key in INHERITABLE_ENV_KEYS:
        value = inherited.get(key)
        if value and not env.get(key):
            env[key] = value
            meta["inherited_env_keys"].append(key)
    meta["token_env_present"] = bool(env.get("SCOUT_CLOUD_MODEL_TOKEN"))
    return env, meta


def load_config_with_overrides(
    path: Path,
    *,
    local_model_base_url_override: str | None = None,
) -> AssistantModelConfig:
    config = load_assistant_model_config(path)
    if local_model_base_url_override:
        config = config.model_copy(
            update={
                "local_model": config.local_model.model_copy(
                    update={"base_url": local_model_base_url_override}
                )
            }
        )
    return config


def run_keypad_pydantic_ai_bridge(
    *,
    rows: list[int],
    cols: list[int],
    grove_ports: list[str] | None,
    active_low: bool,
    duration_seconds: float,
    poll_interval_ms: float,
    debounce_ms: float,
    dry_run: bool,
    simulated_keys: list[str],
    assistant_config_path: Path,
    manifest_dir: Path,
    output_dir: Path,
    output_jsonl: Path | None,
    trace_log_path: Path | None,
    inherit_runtime_env_from_pid: str | None,
    local_model_base_url_override: str | None,
    timeout_seconds: int | None,
    oled_options: dict[str, Any],
    voice_options: dict[str, Any],
    runner_factory: RunnerFactory | None = None,
    voice_executor: VoiceExecutor = execute_command_plan,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    input_dir = output_dir / "inputs"
    result_dir = output_dir / "tool-results"
    input_dir.mkdir(parents=True, exist_ok=True)
    result_dir.mkdir(parents=True, exist_ok=True)
    trace_log = trace_log_path or output_dir / "agent-tool-trace.jsonl"
    feedback_events: list[dict[str, Any]] = []
    key_runs: list[dict[str, Any]] = []
    env, env_meta = inherit_runtime_environment(inherit_runtime_env_from_pid)
    config = load_config_with_overrides(
        assistant_config_path,
        local_model_base_url_override=local_model_base_url_override,
    )
    if timeout_seconds is not None:
        config = config.model_copy(update={"timeout_seconds": timeout_seconds})
    runner = create_configured_scout_agent_planner_runner(
        config,
        environ=env,
        runner_factory=runner_factory,
    )

    emit_feedback(
        feedback_events,
        "ready",
        oled_message="SCOUT AGENT\nREADY\nPAI KEY",
        voice_text_zh="Scout agent 已就緒，等待硬體按鍵。",
        output_dir=output_dir,
        oled_options=oled_options,
        voice_options=voice_options,
        voice_executor=voice_executor,
    )

    def process_keypad_event(keypad_event: dict[str, Any]) -> None:
        key_run = process_agent_key_event(
            keypad_event=keypad_event,
            runner=runner,
            config=config,
            manifest_dir=manifest_dir,
            input_dir=input_dir,
            result_dir=result_dir,
            trace_log_path=trace_log,
            output_dir=output_dir,
            feedback_events=feedback_events,
            oled_options=oled_options,
            voice_options=voice_options,
            voice_executor=voice_executor,
        )
        key_runs.append(key_run)
        append_jsonl([key_run], output_jsonl)

    keypad_dry_run = dry_run or bool(simulated_keys)
    keypad_events = scan_keypad_events(
        rows=rows,
        cols=cols,
        grove_ports=grove_ports,
        active_low=active_low,
        duration_seconds=duration_seconds,
        poll_interval_ms=poll_interval_ms,
        debounce_ms=debounce_ms,
        dry_run=keypad_dry_run,
        simulated_keys=simulated_keys,
        visual_options=_disabled_keypad_visual_options(),
        event_callback=process_keypad_event,
    )
    provider_status = build_scout_agent_planner_provider_status(config, runner)
    status = _summary_status(key_runs)
    summary = {
        "captured_at": utc_now(),
        "artifact_kind": "scout_agent_keypad_pydantic_ai_hardware_test",
        "source": SOURCE,
        "hardware_kind": HARDWARE_KIND,
        "status": status,
        "rows": rows,
        "cols": cols,
        "grove_ports": grove_ports,
        "physical_label_layout": PHYSICAL_LABEL_LAYOUT,
        "active_mode": "active_low" if active_low else "active_high",
        "duration_seconds": duration_seconds,
        "keypad_dry_run": keypad_dry_run,
        "assistant_config_path": str(assistant_config_path),
        "manifest_dir": str(manifest_dir),
        "output_dir": str(output_dir),
        "trace_log_path": str(trace_log),
        "env_inheritance": env_meta,
        "local_model_base_url_override": local_model_base_url_override,
        "provider_status": provider_status.model_dump(mode="json"),
        "key_count": len(keypad_events),
        "agent_key_run_count": len(key_runs),
        "completed_key_run_count": sum(1 for item in key_runs if item["status"] == "completed"),
        "failed_key_run_count": sum(1 for item in key_runs if item["status"] != "completed"),
        "keypad_summary": build_keypad_summary(
            rows=rows,
            cols=cols,
            grove_ports=grove_ports,
            active_low=active_low,
            duration_seconds=duration_seconds,
            dry_run=keypad_dry_run,
            events=keypad_events,
        ),
        "key_runs": key_runs,
        "feedback_events": feedback_events,
        "operator_triggered_alpha_flow": True,
        "phase1_safety_decision_change_allowed": False,
        "safety_level_mutation_allowed": False,
        "live_safety_api_called": False,
        "live_safety_api_mutation_allowed": False,
        "remote_outbound_allowed": False,
        "remote_outbound_send_allowed": False,
        "hardware_control_scope": "operator_triggered_agent_lab_diagnostic_only",
    }
    append_jsonl([summary], output_jsonl)
    return summary


def process_agent_key_event(
    *,
    keypad_event: dict[str, Any],
    runner: ScoutAgentPlannerRunner,
    config: AssistantModelConfig,
    manifest_dir: Path,
    input_dir: Path,
    result_dir: Path,
    trace_log_path: Path,
    output_dir: Path,
    feedback_events: list[dict[str, Any]],
    oled_options: dict[str, Any],
    voice_options: dict[str, Any],
    voice_executor: VoiceExecutor,
) -> dict[str, Any]:
    physical_label = str(keypad_event.get("physical_label") or "")
    action = KEY_TOOL_ACTIONS.get(physical_label, KEY_TOOL_ACTIONS["S1"])
    expected_tool_id = str(action["expected_tool_id"])
    safe_label = physical_label.lower() or "key"
    input_path = input_dir / f"{safe_label}.{expected_tool_id.replace('.', '_')}.request.json"
    output_path = result_dir / f"{safe_label}.{expected_tool_id.replace('.', '_')}.output.json"
    tool_input = dict(action["input"])
    tool_input.update(
        {
            "key": keypad_event.get("key"),
            "physical_label": physical_label,
            "captured_at": keypad_event.get("captured_at"),
            "runtime_safety_truth": False,
            "phase1_safety_decision_change_allowed": False,
            "live_safety_api_called": False,
        }
    )
    if expected_tool_id == "scout.debug.trace_tail":
        tool_input["trace_path"] = str(trace_log_path)
    if expected_tool_id == "scout.voice.preview":
        tool_input["audio_file"] = str(output_dir / "voice-preview-from-agent.wav")
    input_path.write_text(json.dumps(tool_input, ensure_ascii=False, indent=2), encoding="utf-8")
    emit_feedback(
        feedback_events,
        "key_captured",
        oled_message=f"KEY {physical_label}\nPAI START",
        voice_text_zh=f"收到按鍵 {physical_label}，開始呼叫 Pydantic AI。",
        output_dir=output_dir,
        oled_options=oled_options,
        voice_options=voice_options,
        voice_executor=voice_executor,
    )
    prompt = build_hardware_key_prompt(
        keypad_event=keypad_event,
        expected_tool_id=expected_tool_id,
        input_path=input_path,
        output_path=output_path,
        manifest_dir=manifest_dir,
    )
    emit_feedback(
        feedback_events,
        "model_planning",
        oled_message="PAI\nGEMMA3\nPLANNING",
        voice_text_zh="正在呼叫 Pydantic AI 建立工具計畫。",
        output_dir=output_dir,
        oled_options=oled_options,
        voice_options=voice_options,
        voice_executor=voice_executor,
    )
    model_output = ""
    try:
        model_output = runner.run(prompt, timeout_seconds=config.timeout_seconds)
        plan = parse_plan_from_model_output(model_output)
        validate_hardware_key_plan(
            plan,
            expected_tool_id=expected_tool_id,
            input_path=input_path,
            output_path=output_path,
            output_dir=output_dir,
        )
        emit_feedback(
            feedback_events,
            "plan_ok",
            oled_message=f"PLAN OK\n{_short_tool_label(expected_tool_id)}",
            voice_text_zh=f"工具計畫已建立：{action['voice_label_zh']}。",
            output_dir=output_dir,
            oled_options=oled_options,
            voice_options=voice_options,
            voice_executor=voice_executor,
        )
        find_tool_manifest(manifest_dir, expected_tool_id)
        emit_feedback(
            feedback_events,
            "tool_run",
            oled_message=f"TOOL RUN\n{_short_tool_label(expected_tool_id)}",
            voice_text_zh="正在執行 Scout 診斷工具。",
            output_dir=output_dir,
            oled_options=oled_options,
            voice_options=voice_options,
            voice_executor=voice_executor,
        )
        execution = run_agent_tool_plan(
            plan,
            manifest_dir=manifest_dir,
            trace_log_path=trace_log_path,
        )
        run_status = "completed" if execution.status == "completed" else execution.status
        if run_status == "completed":
            emit_feedback(
                feedback_events,
                "done",
                oled_message=f"DONE\n{_short_tool_label(expected_tool_id)}\nTRACE OK",
                voice_text_zh="Scout agent 工具執行完成。",
                output_dir=output_dir,
                oled_options=oled_options,
                voice_options=voice_options,
                voice_executor=voice_executor,
            )
        else:
            emit_feedback(
                feedback_events,
                "tool_failed",
                oled_message=f"ERR TOOL\n{_short_tool_label(expected_tool_id)}",
                voice_text_zh="Scout agent 工具執行失敗，請查看 trace。",
                output_dir=output_dir,
                oled_options=oled_options,
                voice_options=voice_options,
                voice_executor=voice_executor,
            )
        return build_key_run_payload(
            keypad_event=keypad_event,
            status=run_status,
            expected_tool_id=expected_tool_id,
            input_path=input_path,
            output_path=output_path,
            model_output=model_output,
            plan=plan,
            execution=execution.model_dump(mode="json"),
            error=None,
        )
    except Exception as exc:  # noqa: BLE001 - hardware lab runner reports structured failures.
        stage = "model_plan_rejected" if model_output else "model_call_failed"
        emit_feedback(
            feedback_events,
            stage,
            oled_message=f"ERR {stage[:10].upper()}\n{type(exc).__name__}"[:48],
            voice_text_zh="Scout agent 發生錯誤，請查看 OLED 或 JSON trace。",
            output_dir=output_dir,
            oled_options=oled_options,
            voice_options=voice_options,
            voice_executor=voice_executor,
        )
        return build_key_run_payload(
            keypad_event=keypad_event,
            status=stage,
            expected_tool_id=expected_tool_id,
            input_path=input_path,
            output_path=output_path,
            model_output=model_output,
            plan=None,
            execution=None,
            error=f"{type(exc).__name__}: {exc}",
        )


def build_hardware_key_prompt(
    *,
    keypad_event: dict[str, Any],
    expected_tool_id: str,
    input_path: Path,
    output_path: Path,
    manifest_dir: Path,
) -> str:
    user_intent = (
        f"Operator pressed Scout hardware key {keypad_event.get('physical_label')} "
        f"({keypad_event.get('key')}). Return exactly one scout_agent_tool_plan "
        f"calling tool_id {expected_tool_id}. Use input_path {input_path}, "
        f"output_path {output_path}, dry_run true, and authorized_by "
        "operator.hardware_keypad_lab. Do not call /safety/* or mutate runtime safety."
    )
    context = {
        "trigger": "operator_hardware_keypad",
        "keypad_event": keypad_event,
        "expected_tool_id": expected_tool_id,
        "required_input_path": str(input_path),
        "required_output_path": str(output_path),
        "required_dry_run": True,
        "authorized_by": "operator.hardware_keypad_lab",
        "runtime_safety_truth": False,
        "phase1_safety_decision_change_allowed": False,
        "live_safety_api_called": False,
    }
    return build_agent_tool_planning_prompt(
        user_intent=user_intent,
        manifest_dir=manifest_dir,
        context=context,
    )


def parse_plan_from_model_output(model_output: str) -> ScoutAgentToolPlan:
    try:
        return parse_agent_tool_plan(model_output)
    except Exception:
        candidate = _extract_json_object(model_output)
        if candidate == model_output:
            raise
        return parse_agent_tool_plan(candidate)


def validate_hardware_key_plan(
    plan: ScoutAgentToolPlan,
    *,
    expected_tool_id: str,
    input_path: Path,
    output_path: Path,
    output_dir: Path,
) -> None:
    if plan.boundary.live_safety_api_calls_allowed:
        raise ValueError("model plan attempted to allow live safety API calls")
    if plan.boundary.phase1_safety_mutation_allowed:
        raise ValueError("model plan attempted to allow Phase 1 safety mutation")
    if len(plan.tool_calls) != 1:
        raise ValueError("hardware key lab runner expects exactly one tool call")
    call = plan.tool_calls[0]
    if call.tool_id != expected_tool_id:
        raise ValueError(f"unexpected tool_id {call.tool_id}; expected {expected_tool_id}")
    if not call.dry_run:
        raise ValueError("hardware key lab runner requires dry_run=true")
    if call.input_path != str(input_path):
        raise ValueError("model plan did not use the required input_path")
    if call.output_path not in {None, str(output_path)}:
        raise ValueError("model plan used an unexpected output_path")
    if call.authorized_by != "operator.hardware_keypad_lab":
        raise ValueError("model plan must preserve operator hardware key authorization metadata")
    for candidate in (call.input_path, call.output_path):
        if candidate and not _path_is_within(Path(candidate), output_dir):
            raise ValueError("model plan path escaped the output directory")


def build_key_run_payload(
    *,
    keypad_event: dict[str, Any],
    status: str,
    expected_tool_id: str,
    input_path: Path,
    output_path: Path,
    model_output: str,
    plan: ScoutAgentToolPlan | None,
    execution: dict[str, Any] | None,
    error: str | None,
) -> dict[str, Any]:
    payload = {
        "captured_at": utc_now(),
        "artifact_kind": "scout_agent_keypad_pydantic_ai_key_run",
        "source": SOURCE,
        "status": status,
        "keypad_event": keypad_event,
        "expected_tool_id": expected_tool_id,
        "input_path": str(input_path),
        "output_path": str(output_path),
        "model_output_excerpt": model_output[:1000],
        "tool_plan": plan.model_dump(mode="json") if plan else None,
        "execution": execution,
        "error": error,
        "operator_triggered_alpha_flow": True,
        "runtime_safety_truth": False,
        "phase1_safety_decision_change_allowed": False,
        "safety_level_mutation_allowed": False,
        "live_safety_api_called": False,
        "remote_outbound_allowed": False,
        "remote_outbound_send_allowed": False,
        "hardware_control_scope": "operator_triggered_agent_lab_diagnostic_only",
    }
    return payload


def emit_feedback(
    feedback_events: list[dict[str, Any]],
    stage: str,
    *,
    oled_message: str,
    voice_text_zh: str,
    output_dir: Path,
    oled_options: dict[str, Any],
    voice_options: dict[str, Any],
    voice_executor: VoiceExecutor,
) -> None:
    event = {
        "captured_at": utc_now(),
        "artifact_kind": "scout_agent_keypad_feedback_event",
        "stage": stage,
        "oled": emit_oled_feedback(stage=stage, message=oled_message, **oled_options),
        "voice": emit_voice_feedback(
            stage=stage,
            text_zh=voice_text_zh,
            output_dir=output_dir,
            executor=voice_executor,
            **voice_options,
        ),
        "phase1_safety_decision_change_allowed": False,
        "live_safety_api_called": False,
        "remote_outbound_allowed": False,
    }
    feedback_events.append(event)


def emit_oled_feedback(
    *,
    stage: str,
    message: str,
    enabled: bool,
    dry_run: bool,
    bus: Path,
    address: int,
    driver: str,
) -> dict[str, Any]:
    payload = {
        "target": "oled",
        "stage": stage,
        "enabled": enabled,
        "write_status": "disabled",
        "bus": str(bus),
        "address": f"0x{address:02x}",
        "driver": driver,
        "message": _fit_oled_message(message),
        "hardware_control_scope": "diagnostic_display_only",
    }
    if not enabled:
        return payload
    if dry_run:
        payload["write_status"] = "dry_run"
        return payload
    try:
        payload["driver_attempted"] = write_display(
            bus=bus,
            address=address,
            driver=driver,
            message=payload["message"],
        )
        payload["write_status"] = "ok"
    except Exception as exc:  # noqa: BLE001 - debug display failure must not block tool evidence.
        payload["write_status"] = "error"
        payload["error"] = f"{type(exc).__name__}: {exc}"
    return payload


def emit_voice_feedback(
    *,
    stage: str,
    text_zh: str,
    output_dir: Path,
    enabled: bool,
    execute: bool,
    engine: str,
    piper_binary: str,
    piper_model: Path,
    espeak_binary: str,
    espeak_voice: str,
    playback_command: str,
    audio_dir: Path | None,
    executor: VoiceExecutor,
) -> dict[str, Any]:
    voice_dir = audio_dir or output_dir / "voice"
    audio_file = voice_dir / f"{len(list(voice_dir.glob('*.wav'))) + 1:03d}-{_safe_token(stage)}.wav" if voice_dir.exists() else voice_dir / f"001-{_safe_token(stage)}.wav"
    payload = {
        "target": "voice",
        "stage": stage,
        "enabled": enabled,
        "mode": "execute" if execute else "dry_run",
        "engine": engine,
        "text_zh": text_zh,
        "audio_file": str(audio_file),
        "write_status": "disabled",
        "audio_playback_allowed": execute,
        "phase1_safety_decision_change_allowed": False,
        "remote_outbound_allowed": False,
        "hardware_control_scope": "diagnostic_voice_feedback_only",
    }
    if not enabled:
        return payload
    try:
        voice_dir.mkdir(parents=True, exist_ok=True)
        provider = configured_provider_for_engine(
            engine,  # type: ignore[arg-type]
            piper_binary=piper_binary,
            piper_model_path=piper_model,
            espeak_binary=espeak_binary,
            espeak_voice=espeak_voice,
            playback_binary=shlex.split(playback_command),
        )
        plan = provider.command_plan(text_zh=text_zh, audio_file=audio_file)
        payload["command_plan"] = plan.model_dump(mode="json")
        if execute:
            executor(plan)
            payload["write_status"] = "ok"
            payload["executed"] = True
            payload["execution_failed"] = False
        else:
            payload["write_status"] = "dry_run"
            payload["executed"] = False
            payload["execution_failed"] = False
    except CalledProcessError as exc:
        payload["write_status"] = "error"
        payload["executed"] = False
        payload["execution_failed"] = True
        payload["error"] = f"{type(exc).__name__}: {exc}"
        payload["returncode"] = exc.returncode
        payload["stderr"] = exc.stderr
    except Exception as exc:  # noqa: BLE001 - voice feedback failure should be observable, not fatal.
        payload["write_status"] = "error"
        payload["executed"] = False
        payload["execution_failed"] = True
        payload["error"] = f"{type(exc).__name__}: {exc}"
    return payload


def append_jsonl(payloads: list[dict[str, Any]], output_path: Path | None) -> None:
    if output_path is None:
        return
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("a", encoding="utf-8") as handle:
        for payload in payloads:
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def write_json(payload: dict[str, Any], output_path: Path | None) -> None:
    if output_path is None:
        return
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _runtime_env_candidates(mode: str) -> list[tuple[int, dict[str, str]]]:
    if mode != "auto":
        pid = int(mode)
        try:
            env = parse_environ_bytes((Path("/proc") / str(pid) / "environ").read_bytes())
        except Exception:
            return []
        return [(pid, env)]
    candidates: list[tuple[int, dict[str, str], int]] = []
    for proc_dir in Path("/proc").iterdir():
        if not proc_dir.name.isdigit():
            continue
        try:
            env = parse_environ_bytes((proc_dir / "environ").read_bytes())
        except Exception:
            continue
        score = 0
        if env.get("SCOUT_AI_ASSISTANT_PROVIDER") == "pydantic_ai":
            score += 10
        if env.get("SCOUT_AI_ASSISTANT_CONFIG_PATH"):
            score += 5
        if env.get("SCOUT_CLOUD_MODEL_TOKEN"):
            score += 5
        if score:
            candidates.append((int(proc_dir.name), env, score))
    candidates.sort(key=lambda item: (-item[2], item[0]))
    return [(pid, env) for pid, env, _score in candidates]


def _disabled_keypad_visual_options() -> dict[str, Any]:
    return {
        "oled_status": False,
        "oled_dry_run": True,
        "oled_bus": Path("/dev/i2c-1"),
        "oled_address": 0x3C,
        "oled_driver": "sh1107g",
        "led_status": False,
        "led_dry_run": True,
        "led_port": "D5",
        "led_data_gpio": 5,
        "led_clock_gpio": 6,
        "led_blink_seconds": 0.0,
    }


def _summary_status(key_runs: list[dict[str, Any]]) -> str:
    if not key_runs:
        return "no_key_events"
    if all(item["status"] == "completed" for item in key_runs):
        return "completed"
    if any(item["status"] == "completed" for item in key_runs):
        return "partial"
    return "failed"


def _extract_json_object(value: str) -> str:
    stripped = value.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        return stripped
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start >= 0 and end > start:
        return stripped[start : end + 1]
    return value


def _fit_oled_message(message: str) -> str:
    return "\n".join(line[:16] for line in message.splitlines()[:5])


def _short_tool_label(tool_id: str) -> str:
    return tool_id.replace("scout.", "").replace("_", " ")[:16].upper()


def _safe_token(value: str) -> str:
    safe = "".join(char.lower() if char.isalnum() else "-" for char in value)
    while "--" in safe:
        safe = safe.replace("--", "-")
    return safe.strip("-") or "stage"


def _path_is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Trigger Scout Pydantic AI agent tool planning from a hardware keypad with OLED/voice debug feedback."
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--output-jsonl", type=Path)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--trace-log-path", type=Path)
    parser.add_argument("--assistant-config", type=Path, default=DEFAULT_ASSISTANT_CONFIG)
    parser.add_argument("--manifest-dir", type=Path, default=DEFAULT_MANIFEST_DIR)
    parser.add_argument("--inherit-runtime-env-from-pid", default="auto")
    parser.add_argument("--local-model-base-url-override")
    parser.add_argument("--timeout-seconds", type=int)
    parser.add_argument("--grove-ports", type=parse_grove_ports, default=DEFAULT_GROVE_PORTS)
    parser.add_argument("--rows", type=parse_gpio_list)
    parser.add_argument("--cols", type=parse_gpio_list)
    parser.add_argument("--duration-seconds", type=parse_non_negative_float, default=30.0)
    parser.add_argument("--poll-interval-ms", type=parse_positive_float, default=25.0)
    parser.add_argument("--debounce-ms", type=parse_non_negative_float, default=120.0)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--active-low", dest="active_low", action="store_true", default=False)
    mode.add_argument("--active-high", dest="active_low", action="store_false")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--simulate-keys", type=parse_simulated_keys, default=[])
    parser.add_argument("--oled-status", action="store_true")
    parser.add_argument("--oled-bus", type=Path, default=Path("/dev/i2c-1"))
    parser.add_argument("--oled-address", type=parse_address, default=parse_address("0x3c"))
    parser.add_argument("--oled-driver", choices=("sh1107g", "ssd1327", "auto"), default="sh1107g")
    parser.add_argument("--oled-dry-run", action="store_true")
    parser.add_argument("--voice-status", action="store_true")
    parser.add_argument("--voice-execute", action="store_true")
    parser.add_argument("--voice-engine", choices=("piper", "espeak"), default="piper")
    parser.add_argument("--piper-binary", default=DEFAULT_PIPER_BINARY)
    parser.add_argument("--piper-model", type=Path, default=DEFAULT_PIPER_MODEL)
    parser.add_argument("--espeak-binary", default="espeak-ng")
    parser.add_argument("--espeak-voice", default="zh")
    parser.add_argument("--voice-playback-command", default=DEFAULT_PLAYBACK_COMMAND)
    parser.add_argument("--voice-audio-dir", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if (args.rows is None) != (args.cols is None):
        parser.error("--rows and --cols must be provided together")
    if args.rows is None:
        rows, cols = rows_cols_from_grove_ports(args.grove_ports)
        grove_ports = args.grove_ports
    else:
        rows = args.rows
        cols = args.cols or []
        grove_ports = None

    summary = run_keypad_pydantic_ai_bridge(
        rows=rows,
        cols=cols,
        grove_ports=grove_ports,
        active_low=args.active_low,
        duration_seconds=args.duration_seconds,
        poll_interval_ms=args.poll_interval_ms,
        debounce_ms=args.debounce_ms,
        dry_run=args.dry_run,
        simulated_keys=args.simulate_keys,
        assistant_config_path=args.assistant_config,
        manifest_dir=args.manifest_dir,
        output_dir=args.output_dir,
        output_jsonl=args.output_jsonl,
        trace_log_path=args.trace_log_path,
        inherit_runtime_env_from_pid=args.inherit_runtime_env_from_pid,
        local_model_base_url_override=args.local_model_base_url_override,
        timeout_seconds=args.timeout_seconds,
        oled_options={
            "enabled": args.oled_status,
            "dry_run": args.oled_dry_run or args.dry_run,
            "bus": args.oled_bus,
            "address": args.oled_address,
            "driver": args.oled_driver,
        },
        voice_options={
            "enabled": args.voice_status,
            "execute": args.voice_execute,
            "engine": args.voice_engine,
            "piper_binary": args.piper_binary,
            "piper_model": args.piper_model,
            "espeak_binary": args.espeak_binary,
            "espeak_voice": args.espeak_voice,
            "playback_command": args.voice_playback_command,
            "audio_dir": args.voice_audio_dir,
        },
    )
    write_json(summary, args.output)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["status"] in {"completed", "no_key_events"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
