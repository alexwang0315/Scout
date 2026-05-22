from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence


REPO_ROOT = Path(__file__).resolve().parent

REQUIRED_PATHS = (
    "voice_cue_models.py",
    "voice_cue_policy.py",
    "mock_voice_transport.py",
    "voice_tts_provider.py",
    "tools/pi_voice_tts_smoke.py",
    "tools/voice_cue_debug_demo.py",
    "tests/fixtures/voice_cue/demo_cues.json",
    "docs/specs/scout-voice-cue-layer.md",
    "docs/admin/scout-machine-deployment-smoke.md",
    "tests/test_voice_cue_models.py",
    "tests/test_voice_cue_policy.py",
    "tests/test_mock_voice_transport.py",
    "tests/test_voice_tts_provider.py",
    "tests/test_pi_voice_tts_smoke.py",
    "tests/test_voice_cue_debug_demo.py",
)

SPEC_TOKENS = (
    "wilderness safety black box",
    "outbound awareness channel",
    "safety_decision_change_allowed=false",
    "remote_outbound_allowed=false",
    "hardware_control_allowed=false",
    "read_only_model_interpretation",
    "Piper TTS",
    "eSpeak NG",
    "MockVoiceTransport",
    "voice_cue_queued",
    "voice_cue_state_changed",
    "Scout Machine Activation Status",
    "scout.local",
    "piper-tts==1.4.2",
    "zh_CN-huayan-medium",
    "bluez-alsa-utils",
    "LS-S01",
    "34:D2:CF:30:6F:2C",
    "bluealsa:DEV=34:D2:CF:30:6F:2C,PROFILE=a2dp,SRV=org.bluealsa",
    "scout-ls-s01-autoconnect.service",
    "/usr/local/sbin/scout-connect-ls-s01.sh",
    "中文註釋",
)

RUNBOOK_TOKENS = (
    "pi_voice_tts_smoke.py",
    "voice_cue_debug_demo.py",
    "--engine piper",
    "--output-jsonl",
    "不播放真音訊",
    "不呼叫 `/safety/*`",
    "不送 remote outbound",
    "不控制硬體",
)

FORBIDDEN_SOURCE_TOKENS: dict[str, tuple[str, ...]] = {
    "voice_cue_models.py": (
        "safety_api",
        "SafetyRuntimeSession",
        "requests",
        "httpx",
        "subprocess",
    ),
    "mock_voice_transport.py": (
        "safety_api",
        "SafetyRuntimeSession",
        "requests",
        "httpx",
        "subprocess",
        "bluetooth",
        "pyaudio",
        "sounddevice",
    ),
    "voice_cue_policy.py": (
        "safety_api",
        "SafetyRuntimeSession",
        "requests",
        "httpx",
        "subprocess",
    ),
    "tools/voice_cue_debug_demo.py": (
        "execute_command_plan",
        "subprocess",
        "requests",
        "httpx",
        "urllib",
        "safety_api",
        "/safety/",
        "mock_outbound_transport",
        "bluetooth",
    ),
}


@dataclass(frozen=True)
class PathCheck:
    name: str
    required_paths: tuple[str, ...]


def build_voice_cue_readiness_check(repo_root: Path | str = REPO_ROOT) -> dict[str, Any]:
    root = Path(repo_root)
    checks: dict[str, Any] = {}
    missing_required: list[str] = []

    required_paths = _check_required_paths(root, REQUIRED_PATHS)
    checks["required_paths"] = required_paths
    missing_required.extend(required_paths["missing"])

    spec = _check_tokens(root / "docs/specs/scout-voice-cue-layer.md", root, SPEC_TOKENS, "spec_token")
    checks["spec"] = spec
    missing_required.extend(spec["missing"])

    runbook = _check_tokens(
        root / "docs/admin/scout-machine-deployment-smoke.md",
        root,
        RUNBOOK_TOKENS,
        "runbook_token",
    )
    checks["runbook"] = runbook
    missing_required.extend(runbook["missing"])

    static_boundaries = _check_static_boundaries(root)
    checks["static_boundaries"] = static_boundaries
    missing_required.extend(static_boundaries["missing"])

    missing_required = sorted(set(missing_required))
    return {
        "ok": not missing_required,
        "repo_root": str(root),
        "checks": checks,
        "missing_required_artifacts": missing_required,
    }


def _check_required_paths(root: Path, required_paths: Sequence[str]) -> dict[str, Any]:
    missing = sorted(path for path in required_paths if not (root / path).exists())
    return {
        "ok": not missing,
        "required": len(required_paths),
        "present": len(required_paths) - len(missing),
        "missing": missing,
    }


def _check_tokens(
    path: Path,
    root: Path,
    tokens: Sequence[str],
    prefix: str,
) -> dict[str, Any]:
    if not path.exists():
        return {"ok": False, "missing": [str(path.relative_to(root))]}
    source = path.read_text(encoding="utf-8")
    missing = [f"{prefix}:{token}" for token in tokens if token not in source]
    return {"ok": not missing, "missing": missing}


def _check_static_boundaries(root: Path) -> dict[str, Any]:
    missing: list[str] = []
    for relative_path, forbidden_tokens in FORBIDDEN_SOURCE_TOKENS.items():
        path = root / relative_path
        if not path.exists():
            missing.append(relative_path)
            continue
        source = path.read_text(encoding="utf-8")
        missing.extend(
            f"forbidden_token:{relative_path}:{token}"
            for token in forbidden_tokens
            if token in source
        )
    return {"ok": not missing, "missing": sorted(missing)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the Scout Voice Cue Layer readiness check.")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)
    result = build_voice_cue_readiness_check(args.repo_root)
    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
