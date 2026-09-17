import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _write_executable(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


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


def test_dashboard_launcher_manages_a_local_qgis_worker_by_default(
    tmp_path: Path,
) -> None:
    runtime = tmp_path / "runtime"
    bin_dir = runtime / "bin"
    bin_dir.mkdir(parents=True)
    ready = tmp_path / "worker-ready"
    stopped = tmp_path / "worker-stopped"
    dashboard_started = tmp_path / "dashboard-started"
    token_file = tmp_path / "worker-token"
    token_file.write_text("test-worker-token-0123456789abcdef\n", encoding="utf-8")

    _write_executable(
        bin_dir / "python",
        """#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" == "-c" ]]; then
  exit 0
fi
if [[ "${1:-}" == "-" ]]; then
  [[ -f "${FAKE_QGIS_READY_FILE}" ]]
  exit
fi
[[ -f "${FAKE_QGIS_READY_FILE}" ]]
touch "${FAKE_DASHBOARD_STARTED_FILE}"
""",
    )
    for executable in ("osmium", "grass"):
        _write_executable(bin_dir / executable, "#!/usr/bin/env bash\nexit 0\n")
    worker_launcher = tmp_path / "fake-qgis-worker.sh"
    _write_executable(
        worker_launcher,
        """#!/usr/bin/env bash
set -euo pipefail
touch "${FAKE_QGIS_READY_FILE}"
trap 'touch "${FAKE_QGIS_STOPPED_FILE}"; exit 0' TERM INT
while true; do sleep 0.05; done
""",
    )

    completed = subprocess.run(
        [str(ROOT / "tools" / "run_dashboard_workspace.sh"), "--port", "9099"],
        cwd=ROOT,
        env={
            **os.environ,
            "SCOUT_DASHBOARD_VENV": str(runtime),
            "SCOUT_DASHBOARD_QGIS_WORKER_LAUNCHER": str(worker_launcher),
            "SCOUT_DASHBOARD_QGIS_WORKER_LOG": str(tmp_path / "worker.log"),
            "SCOUT_DASHBOARD_QGIS_WORKER_START_TIMEOUT": "2",
            "SCOUT_QGIS_WORKER_TOKEN_FILE": str(token_file),
            "FAKE_QGIS_READY_FILE": str(ready),
            "FAKE_QGIS_STOPPED_FILE": str(stopped),
            "FAKE_DASHBOARD_STARTED_FILE": str(dashboard_started),
        },
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert ready.is_file()
    assert dashboard_started.is_file()
    assert stopped.is_file()
    assert "QGIS worker started with Dashboard" in completed.stdout


def test_dashboard_launcher_exposes_worker_autostart_opt_out() -> None:
    script = (ROOT / "tools" / "run_dashboard_workspace.sh").read_text(
        encoding="utf-8"
    )

    assert 'SCOUT_DASHBOARD_AUTO_QGIS_WORKER:-true' in script
    assert 'SCOUT_DASHBOARD_QGIS_WORKER_REQUIRED:-false' in script


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
