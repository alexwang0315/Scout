"""Host adapter for the prepared local Scout QGIS profile and Worker launcher."""

from __future__ import annotations

import hmac
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from qgis_runtime_control import QgisRuntimeControlCode as Code
from qgis_runtime_control import QgisRuntimeController, QgisRuntimeUnavailable
from qgis_spatial_backend import QgisMcpHttpTransport, QgisSpatialBackend, QgisSpatialBackendConfig
from qgis_spatial_contracts import QgisBackendStatus


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise HTTPError(req.full_url, code, "Local Worker redirects are not allowed", headers, fp)


class _LocalWorkerTransport(QgisMcpHttpTransport):
    def get_json(self, url: str, *, timeout_s: float):
        opener = build_opener(ProxyHandler({}), _NoRedirect())
        request = Request(url, headers=self._headers())
        with opener.open(request, timeout=timeout_s) as response:
            raw = response.read(1_048_577)
        if len(raw) > 1_048_576:
            raise ValueError("Local Worker status exceeds limit")
        return json.loads(raw)


class LocalQgisRuntimeHost:
    def __init__(
        self, *, repo_root: Path, config: QgisSpatialBackendConfig,
        environ: Mapping[str, str], home: Path, platform: str = sys.platform,
    ) -> None:
        self.repo_root = repo_root
        self.config = config
        self.environ = dict(environ)
        self.home = home
        self.platform = platform
        self.profile_root = home / ".scout-fusion/qgis-desktop"
        self.token_file = Path(environ.get("SCOUT_QGIS_WORKER_TOKEN_FILE") or self.profile_root / "runtime/worker-token")
        self.runtime_root = self.token_file.parent
        self.connection_file = Path(environ.get("QGIS_MCP_CONNECTION_FILE") or home / ".qgis-mcp/connection.json")
        self.server_root = Path(environ.get("SCOUT_QGIS_MCP_PYTHONPATH") or self.profile_root / "profiles/scout/python/plugins/qgis_agent_mcp/_server")
        self.python = Path(environ.get("SCOUT_DASHBOARD_VENV") or repo_root / "venv") / "bin/python"
        self.launcher = repo_root / "tools/run_qgis_worker.sh"
        self.qgis_app = Path(environ.get("SCOUT_QGIS_CONTENTS") or "/Applications/QGIS-LTR.app/Contents").parent
        self.backend = QgisSpatialBackend(
            config=config, transport=_LocalWorkerTransport(auth_token=config.worker_token),
        )
        self._worker: subprocess.Popen | None = None

    def configuration_issue(self) -> Code | None:
        if self.config.fixture_mode:
            return Code.FIXTURE_MODE
        if not self.config.enabled or not self.config.worker_url:
            return Code.CONFIGURATION_REQUIRED
        try:
            url = urlparse(self.config.worker_url)
            if url.hostname not in {"127.0.0.1", "localhost"}:
                return Code.REMOTE_MANAGED
            if (url.scheme != "http" or url.username or url.password or url.query or url.fragment
                    or url.path not in {"", "/"} or not url.port):
                return Code.CONFIGURATION_REQUIRED
            token = self.token_file.read_text(encoding="utf-8").strip()
            if (len(token) < 32 or not self.config.worker_token
                    or not hmac.compare_digest(token, self.config.worker_token)):
                return Code.CONFIGURATION_REQUIRED
            if (not self.launcher.is_file() or not os.access(self.python, os.X_OK)
                    or not self.server_root.is_dir()
                    or self.environ.get("SCOUT_QGIS_WORKER_ENABLED", "true").lower() not in {"1", "true", "yes", "on"}):
                return Code.CONFIGURATION_REQUIRED
        except (OSError, ValueError, UnicodeError):
            return Code.CONFIGURATION_REQUIRED
        return None

    def probe(self, project_id: str) -> QgisBackendStatus:
        return self.backend.status(project_id=project_id)

    def worker_listening(self) -> bool:
        return self._port_open(urlparse(self.config.worker_url or "").port)

    def worker_authenticated(self) -> bool:
        try:
            payload = self.backend.transport.get_json(
                (self.config.worker_url or "").rstrip("/") + "/capabilities", timeout_s=5,
            )
            return (
                isinstance(payload, dict)
                and payload.get("schema_version") == "scout_qgis_worker_capabilities.v0_1"
                and "terrain_route_hypothesis.v1" in (payload.get("workflows") or [])
                and payload.get("candidate_only") is True
                and payload.get("runtime_safety_truth") is False
            )
        except (OSError, ValueError, URLError):
            return False

    @staticmethod
    def _port_open(port: int | None) -> bool:
        if not port or not 0 < port < 65536:
            return False
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return True
        except OSError:
            return False

    def _bridge_present(self) -> bool:
        try:
            if self.connection_file.stat().st_size > 16_384:
                return False
            value = json.loads(self.connection_file.read_text(encoding="utf-8"))
            return isinstance(value, dict) and self._port_open(int(value.get("port", 0)))
        except (OSError, ValueError, TypeError):
            return False

    def _qgis_running(self) -> bool:
        result = subprocess.run(
            ["/usr/bin/pgrep", "-u", str(os.getuid()), "-x", "QGIS"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=5, check=False,
        )
        if result.returncode not in {0, 1}:
            raise QgisRuntimeUnavailable(Code.QGIS_SESSION_REQUIRES_ATTENTION)
        return result.returncode == 0

    def ensure_qgis(self) -> str:
        if self._bridge_present():
            return "existing_qgis_preserved"
        if self.platform != "darwin":
            raise QgisRuntimeUnavailable(Code.UNSUPPORTED_HOST)
        try:
            if self._qgis_running():
                raise QgisRuntimeUnavailable(Code.QGIS_SESSION_REQUIRES_ATTENTION)
            if not self.qgis_app.is_dir() or not (self.profile_root / "profiles/scout").is_dir():
                raise QgisRuntimeUnavailable(Code.CONFIGURATION_REQUIRED)
            # QGIS appends /profiles itself. Do not launch a second or default profile.
            subprocess.run(
                ["/usr/bin/open", "-a", str(self.qgis_app), "--args", "--profiles-path",
                 str(self.profile_root), "--profile", "scout", "--nologo", "--noversioncheck"],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=10, check=True,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise QgisRuntimeUnavailable(Code.START_FAILED) from exc
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            if self._bridge_present():
                return "qgis_started"
            time.sleep(1)
        raise QgisRuntimeUnavailable(Code.START_TIMEOUT)

    def start_worker(self) -> str:
        if self._worker is not None and self._worker.poll() is None:
            return "worker_already_starting"
        issue = self.configuration_issue()
        if issue:
            raise QgisRuntimeUnavailable(issue)
        if self.worker_listening():
            if self.worker_authenticated():
                return "existing_worker_preserved"
            raise QgisRuntimeUnavailable(Code.PORT_IN_USE)
        env = {
            **self.environ,
            "HOME": str(self.home),
            "SCOUT_QGIS_WORKER_HOST": "127.0.0.1",
            "SCOUT_QGIS_WORKER_PORT": str(urlparse(self.config.worker_url or "").port),
            "SCOUT_QGIS_WORKER_TOKEN_FILE": str(self.token_file),
            "QGIS_MCP_CONNECTION_FILE": str(self.connection_file),
            "SCOUT_QGIS_MCP_PYTHONPATH": str(self.server_root),
        }
        self.runtime_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(self.runtime_root / "qgis-worker-navigation.log", os.O_CREAT | os.O_APPEND | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        try:
            with os.fdopen(fd, "ab") as log:
                self._worker = subprocess.Popen(
                    ["/bin/bash", str(self.launcher)], cwd=self.repo_root, env=env,
                    stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
        except (OSError, subprocess.SubprocessError) as exc:
            raise QgisRuntimeUnavailable(Code.START_FAILED) from exc
        return "worker_started"


def create_local_qgis_runtime_controller(*, repo_root: Path) -> QgisRuntimeController:
    host = LocalQgisRuntimeHost(
        repo_root=repo_root, config=QgisSpatialBackendConfig.from_env(),
        environ=os.environ, home=Path.home(),
    )
    return QgisRuntimeController(host=host, runtime_root=host.runtime_root)
