from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_runtime_scripts_are_directly_executable_bash_entrypoints() -> None:
    for relative_path in (
        "tools/run_dashboard_workspace.sh",
        "tools/run_qgis_worker.sh",
        "tools/setup_dashboard_workspace_runtime.sh",
    ):
        script_path = ROOT / relative_path
        script = script_path.read_text(encoding="utf-8")

        assert script.startswith("#!/usr/bin/env bash\n")
        assert script_path.stat().st_mode & 0o100


def test_dashboard_launcher_reuses_persistent_qgis_worker_credentials() -> None:
    script = (ROOT / "tools" / "run_dashboard_workspace.sh").read_text(
        encoding="utf-8"
    )

    assert "SCOUT_QGIS_WORKER_TOKEN_FILE" in script
    assert 'export SCOUT_QGIS_ENABLED="${SCOUT_QGIS_ENABLED:-true}"' in script
    assert "SCOUT_QGIS_WORKER_URL" in script
    assert "SCOUT_QGIS_LOCAL_ENDPOINT_REQUIRED" in script


def test_runtime_setup_keeps_qgis_worker_token_and_shortcut_persistent() -> None:
    script = (ROOT / "tools" / "setup_dashboard_workspace_runtime.sh").read_text(
        encoding="utf-8"
    )

    assert "secrets.token_urlsafe" in script
    assert "run_qgis_worker.sh" in script
    assert "scout-qgis-worker" in script


def test_qgis_worker_launcher_uses_the_same_persistent_token_file() -> None:
    script = (ROOT / "tools" / "run_qgis_worker.sh").read_text(encoding="utf-8")

    assert "SCOUT_QGIS_WORKER_TOKEN_FILE" in script
    assert "QGIS_MCP_CONNECTION_FILE" in script
    assert 'SCOUT_QGIS_MCP_COMMAND_JSON=' in script
    assert "shell=False" not in script
