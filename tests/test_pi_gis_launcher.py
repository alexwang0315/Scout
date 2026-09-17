from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "deploy" / "pi-gis" / "launch-qgis-mcp.sh"


def test_pi_gis_launcher_is_shell_syntax_valid() -> None:
    completed = subprocess.run(
        ["sh", "-n", str(LAUNCHER)],
        capture_output=True,
        check=False,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr


def test_pi_gis_launcher_does_not_depend_on_xvfb_run_pid1_signal_handshake() -> None:
    script = LAUNCHER.read_text(encoding="utf-8")

    assert "xvfb-run" not in script
    assert "Xvfb" in script
    assert "xauth add" in script
    assert "/tmp/.X11-unix/X${display_number}" in script
    assert "-nolisten tcp" in script
    assert "exec qgis" in script


def test_pi_gis_launcher_keeps_connection_and_runtime_state_bounded() -> None:
    script = LAUNCHER.read_text(encoding="utf-8")

    assert "SCOUT_QGIS_STATE_ROOT" in script
    assert "QGIS_MCP_CONNECTION_FILE" in script
    assert 'chmod 0700' in script
    assert 'case "${display_number}" in' in script
