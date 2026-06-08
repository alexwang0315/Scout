"""Sandbox verification for generated capability packages."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping
from pathlib import Path, PurePosixPath

from scout.schemas.capability import CapabilityRuntime, GeneratedCapabilityPackage
from scout.schemas.runtime import SandboxResult


DEFAULT_TIMEOUT_SECONDS = 10.0
MAX_PACKAGE_FILES = 20
MAX_FILE_BYTES = 32_768
MAX_PACKAGE_BYTES = 65_536
DISALLOWED_PATTERNS: tuple[str, ...] = (
    "subprocess",
    "os.system",
    "socket",
    "requests",
    "httpx",
    "urllib",
    "shutil.rmtree",
    "open('/etc')",
    "open('/home')",
    ".env",
    "API_KEY",
    "SECRET",
    "TOKEN",
    "rm -rf",
)
_RESERVED_SANDBOX_PATHS = {"sitecustomize.py"}


class SandboxRunner:
    """Verify generated Python capability packages without installing them."""

    def __init__(
        self,
        *,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        python_executable: str | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.timeout_seconds = timeout_seconds
        self.python_executable = python_executable or sys.executable

    def verify(self, package: GeneratedCapabilityPackage) -> SandboxResult:
        return self.run(package)

    def run(self, package: GeneratedCapabilityPackage) -> SandboxResult:
        started_at = time.monotonic()
        findings = _package_findings(package)
        if findings:
            return SandboxResult(
                passed=False,
                test_summary="Sandbox rejected generated package before execution.",
                security_findings=findings,
                resource_usage=_resource_usage(
                    started_at,
                    timeout_seconds=self.timeout_seconds,
                    files_written=0,
                ),
            )

        with tempfile.TemporaryDirectory(prefix="scout-sandbox-") as temp_dir:
            sandbox_path = Path(temp_dir)
            _write_package_files(sandbox_path, package.files)
            _write_package_files(sandbox_path, package.tests)
            _write_network_blocker(sandbox_path)

            completed = _run_pytest(
                sandbox_path,
                timeout_seconds=self.timeout_seconds,
                python_executable=self.python_executable,
            )

        if isinstance(completed, subprocess.TimeoutExpired):
            return SandboxResult(
                passed=False,
                stdout=_coerce_output(completed.stdout),
                stderr=_coerce_output(completed.stderr),
                test_summary=f"pytest timed out after {self.timeout_seconds:g}s",
                security_findings=[],
                resource_usage=_resource_usage(
                    started_at,
                    timeout_seconds=self.timeout_seconds,
                    files_written=len(package.files) + len(package.tests),
                    timed_out=True,
                ),
            )

        return SandboxResult(
            passed=completed.returncode == 0,
            stdout=completed.stdout,
            stderr=completed.stderr,
            test_summary=_pytest_summary(completed),
            security_findings=[],
            resource_usage=_resource_usage(
                started_at,
                timeout_seconds=self.timeout_seconds,
                files_written=len(package.files) + len(package.tests),
                returncode=completed.returncode,
            ),
        )


def _package_findings(package: GeneratedCapabilityPackage) -> list[str]:
    findings: list[str] = []
    if package.spec.runtime is not CapabilityRuntime.PYTHON:
        findings.append(
            f"Unsupported generated capability runtime: {package.spec.runtime.value}"
        )
    if not package.files:
        findings.append("Generated package has no implementation files.")
    if not package.tests:
        findings.append("Generated package has no sandbox tests.")

    file_count = len(package.files) + len(package.tests)
    if file_count > MAX_PACKAGE_FILES:
        findings.append(
            f"Generated package has {file_count} files; limit is {MAX_PACKAGE_FILES}."
        )

    total_bytes = 0
    seen_paths: dict[str, str] = {}
    for group_name, files in (("file", package.files), ("test", package.tests)):
        for relative_path, content in files.items():
            size_bytes = len(content.encode("utf-8"))
            total_bytes += size_bytes
            if size_bytes > MAX_FILE_BYTES:
                findings.append(
                    f"{group_name}:{relative_path} is {size_bytes} bytes; "
                    f"limit is {MAX_FILE_BYTES}."
                )
            safe_path = _safe_relative_path(relative_path)
            if safe_path is None:
                findings.append(f"{group_name}:{relative_path} is not a safe path.")
            else:
                normalized = safe_path.as_posix()
                if normalized in _RESERVED_SANDBOX_PATHS:
                    findings.append(
                        f"{group_name}:{relative_path} uses a reserved sandbox path."
                    )
                previous_group = seen_paths.get(normalized)
                if previous_group is not None:
                    findings.append(
                        f"{group_name}:{relative_path} duplicates {previous_group}:{normalized}."
                    )
                seen_paths[normalized] = group_name
            findings.extend(
                _disallowed_pattern_findings(group_name, relative_path, content)
            )
    if total_bytes > MAX_PACKAGE_BYTES:
        findings.append(
            f"Generated package is {total_bytes} bytes; limit is {MAX_PACKAGE_BYTES}."
        )
    return findings


def _safe_relative_path(relative_path: str) -> Path | None:
    if "\\" in relative_path:
        return None
    path = PurePosixPath(relative_path)
    if path.is_absolute() or not path.parts:
        return None
    if any(part in {"", ".", ".."} for part in path.parts):
        return None
    return Path(*path.parts)


def _disallowed_pattern_findings(
    group_name: str,
    relative_path: str,
    content: str,
) -> list[str]:
    haystacks = {
        "path": relative_path,
        "content": content,
    }
    findings: list[str] = []
    for location, haystack in haystacks.items():
        normalized_haystack = haystack.casefold()
        for pattern in DISALLOWED_PATTERNS:
            if pattern.casefold() in normalized_haystack:
                findings.append(
                    f"{group_name}:{relative_path} {location} contains disallowed pattern {pattern!r}."
                )
    return findings


def _write_package_files(
    sandbox_path: Path,
    files: Mapping[str, str],
) -> None:
    for relative_path, content in files.items():
        safe_path = _safe_relative_path(relative_path)
        if safe_path is None:
            raise ValueError(
                f"Unsafe sandbox path passed after validation: {relative_path}"
            )
        target = sandbox_path / safe_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


def _write_network_blocker(sandbox_path: Path) -> None:
    (sandbox_path / "sitecustomize.py").write_text(
        "\n".join(
            [
                "from __future__ import annotations",
                "import socket",
                "",
                "_MESSAGE = 'Scout sandbox blocks network access'",
                "",
                "def _blocked(*args, **kwargs):",
                "    raise RuntimeError(_MESSAGE)",
                "",
                "socket.socket = _blocked",
                "socket.create_connection = _blocked",
                "socket.getaddrinfo = _blocked",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _run_pytest(
    sandbox_path: Path,
    *,
    timeout_seconds: float,
    python_executable: str,
) -> subprocess.CompletedProcess[str] | subprocess.TimeoutExpired:
    try:
        return subprocess.run(
            [python_executable, "-m", "pytest", "-q", str(sandbox_path)],
            cwd=sandbox_path,
            env=_sandbox_env(sandbox_path),
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        return exc


def _sandbox_env(sandbox_path: Path) -> dict[str, str]:
    env = {
        "HOME": str(sandbox_path / "home"),
        "NO_PROXY": "*",
        "PATH": os.environ.get("PATH", ""),
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "PYTHONPATH": str(sandbox_path),
        "TMPDIR": str(sandbox_path / "tmp"),
    }
    (sandbox_path / "home").mkdir(exist_ok=True)
    (sandbox_path / "tmp").mkdir(exist_ok=True)
    return env


def _pytest_summary(completed: subprocess.CompletedProcess[str]) -> str:
    output = "\n".join([completed.stdout, completed.stderr])
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if lines:
        return lines[-1].strip("= ")
    return f"pytest exited with code {completed.returncode}"


def _coerce_output(output: str | bytes | None) -> str:
    if output is None:
        return ""
    if isinstance(output, bytes):
        return output.decode(errors="replace")
    return output


def _resource_usage(
    started_at: float,
    *,
    timeout_seconds: float,
    files_written: int,
    returncode: int | None = None,
    timed_out: bool = False,
) -> dict[str, float | int | bool | None]:
    return {
        "seconds": round(time.monotonic() - started_at, 4),
        "timeout_seconds": timeout_seconds,
        "files_written": files_written,
        "returncode": returncode,
        "timed_out": timed_out,
    }


__all__ = [
    "DEFAULT_TIMEOUT_SECONDS",
    "DISALLOWED_PATTERNS",
    "MAX_FILE_BYTES",
    "MAX_PACKAGE_BYTES",
    "MAX_PACKAGE_FILES",
    "SandboxRunner",
]
