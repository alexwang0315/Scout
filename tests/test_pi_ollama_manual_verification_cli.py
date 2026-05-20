from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from assistant_readiness_check import REQUIRED_PATHS


ROOT = Path(__file__).resolve().parents[1]
CLI_PATH = ROOT / "pi_ollama_manual_verification_cli.py"
RESULT_FIXTURE = ROOT / "tests" / "fixtures" / "hardware" / "pi_ollama_manual_verification.example.json"
INDEX_FIXTURE = (
    ROOT
    / "tests"
    / "fixtures"
    / "hardware"
    / "pi_ollama_manual_verification.index.example.json"
)
DOC_PATH = ROOT / "docs" / "admin" / "pi-ollama-manual-verification.md"
SPEC_PATH = ROOT / "docs" / "specs" / "scout-cross-surface-ai-assistant.md"


def test_cli_renders_manual_result_summary_read_only() -> None:
    completed = subprocess.run(
        [sys.executable, str(CLI_PATH), "--result", str(RESULT_FIXTURE)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert "Manual Pi/Ollama verification summary" in completed.stdout
    assert "operator_observed_latency_ms=5700" in completed.stdout
    assert "read_only=true" in completed.stdout
    assert "phase1_state_changed=false" in completed.stdout
    assert "hardware_controlled=false" in completed.stdout
    assert "/Users/alexwang0315/.scout/assistant-models.json" not in completed.stdout
    assert completed.stderr == ""


def test_cli_renders_manual_index_summary_read_only() -> None:
    completed = subprocess.run(
        [sys.executable, str(CLI_PATH), "--index", str(INDEX_FIXTURE)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert "Manual Pi/Ollama verification index summary" in completed.stdout
    assert "entry_count=1" in completed.stdout
    assert "fixture_path=tests/fixtures/hardware/pi_ollama_manual_verification.example.json" in completed.stdout
    assert "outbound_sent=false" in completed.stdout
    assert "not part of the assistant readiness gate" in completed.stdout
    assert completed.stderr == ""


def test_cli_requires_exactly_one_input_mode() -> None:
    completed = subprocess.run(
        [sys.executable, str(CLI_PATH), "--result", str(RESULT_FIXTURE), "--index", str(INDEX_FIXTURE)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert "not allowed with argument" in completed.stderr


def test_cli_is_offline_read_only_and_optional() -> None:
    source = CLI_PATH.read_text(encoding="utf-8")

    assert "write_text" not in source
    assert "open(" not in source
    assert "tests/fixtures/hardware/pi_ollama_manual_verification.index.example.json" not in REQUIRED_PATHS
    for forbidden in (
        "requests",
        "httpx",
        "urllib",
        "socket",
        "/assistant/query",
        "/assistant/status",
        "/safety/",
        "ObservedFactWriter",
        "BrainFileStore",
        "IncidentStore",
        "send_outbound",
        "MockOutboundTransport",
    ):
        assert forbidden not in source


def test_docs_track_slice8_cli_renderer_and_next_slice() -> None:
    doc_source = DOC_PATH.read_text(encoding="utf-8")
    spec_source = SPEC_PATH.read_text(encoding="utf-8")

    for source in (doc_source, spec_source):
        for token in (
            "Milestone 10.2 Slice 8",
            "pi_ollama_manual_verification_cli.py",
            "--result",
            "--index",
            "read-only CLI renderer",
            "not part of the assistant readiness gate",
        ):
            assert token in source

    assert "Milestone 10.2 Slice 8 read-only CLI renderer is complete when" in spec_source
    assert "## Next Slice Candidates" in spec_source
