from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from voice_cue_readiness_check import (
    FORBIDDEN_SOURCE_TOKENS,
    REQUIRED_PATHS,
    RUNBOOK_TOKENS,
    SPEC_TOKENS,
    build_voice_cue_readiness_check,
)


ROOT = Path(__file__).resolve().parents[1]


def test_current_voice_cue_layer_passes_readiness_check() -> None:
    result = build_voice_cue_readiness_check(ROOT)

    assert result["ok"], result["missing_required_artifacts"]
    assert result["checks"]["required_paths"]["missing"] == []
    assert result["checks"]["spec"]["missing"] == []
    assert result["checks"]["runbook"]["missing"] == []
    assert result["checks"]["static_boundaries"]["missing"] == []


def test_missing_voice_cue_required_paths_and_tokens_are_reported(tmp_path: Path) -> None:
    _write_complete_minimal_repo(tmp_path)
    (tmp_path / "voice_cue_models.py").unlink()
    _write(tmp_path / "docs/specs/scout-voice-cue-layer.md", "wilderness safety black box")
    _write(tmp_path / "docs/admin/scout-machine-deployment-smoke.md", "pi_voice_tts_smoke.py")

    result = build_voice_cue_readiness_check(tmp_path)

    assert result["ok"] is False
    assert "voice_cue_models.py" in result["missing_required_artifacts"]
    assert result["checks"]["spec"]["missing"] == [
        f"spec_token:{token}" for token in SPEC_TOKENS if token != "wilderness safety black box"
    ]
    assert result["checks"]["runbook"]["missing"] == [
        f"runbook_token:{token}" for token in RUNBOOK_TOKENS if token != "pi_voice_tts_smoke.py"
    ]


def test_forbidden_voice_cue_source_tokens_are_reported(tmp_path: Path) -> None:
    _write_complete_minimal_repo(tmp_path)
    _write(tmp_path / "mock_voice_transport.py", "requests.post('https://example.invalid')")

    result = build_voice_cue_readiness_check(tmp_path)

    assert result["ok"] is False
    assert (
        "forbidden_token:mock_voice_transport.py:requests"
        in result["checks"]["static_boundaries"]["missing"]
    )


def test_voice_cue_readiness_cli_prints_json(tmp_path: Path) -> None:
    _write_complete_minimal_repo(tmp_path)
    (tmp_path / "tools" / "voice_cue_debug_demo.py").unlink()

    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "voice_cue_readiness_check.py"),
            "--repo-root",
            str(tmp_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 1
    payload = json.loads(completed.stdout)
    assert payload["ok"] is False
    assert "tools/voice_cue_debug_demo.py" in payload["missing_required_artifacts"]


def _write_complete_minimal_repo(root: Path) -> None:
    for path in REQUIRED_PATHS:
        _write(root / path, "read-only voice cue placeholder")
    _write(root / "docs/specs/scout-voice-cue-layer.md", "\n".join(SPEC_TOKENS))
    _write(root / "docs/admin/scout-machine-deployment-smoke.md", "\n".join(RUNBOOK_TOKENS))
    for path, forbidden_tokens in FORBIDDEN_SOURCE_TOKENS.items():
        _write(root / path, f"safe source without {len(forbidden_tokens)} forbidden imports")


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
