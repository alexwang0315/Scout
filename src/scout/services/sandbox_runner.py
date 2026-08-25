"""Sandbox verification for generated capability packages."""

from __future__ import annotations

import ast
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping
from pathlib import Path, PurePosixPath

from scout.schemas.capability import CapabilityRuntime, GeneratedCapabilityPackage
from scout.schemas.runtime import SandboxResult


DEFAULT_TIMEOUT_SECONDS = 30.0
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
_SAFE_IMPORT_ROOTS = {
    "__future__",
    "collections",
    "csv",
    "datetime",
    "decimal",
    "functools",
    "itertools",
    "json",
    "math",
    "operator",
    "pytest",
    "re",
    "sitecustomize",
    "statistics",
    "string",
    "time",
    "typing",
}
_FORBIDDEN_CALL_NAMES = {
    "__import__",
    "breakpoint",
    "compile",
    "delattr",
    "eval",
    "exec",
    "getattr",
    "globals",
    "input",
    "locals",
    "open",
    "setattr",
    "vars",
}
_FORBIDDEN_METHOD_NAMES = {
    "chmod",
    "mkdir",
    "open",
    "popen",
    "remove",
    "rename",
    "replace",
    "rmdir",
    "spawn",
    "system",
    "touch",
    "unlink",
    "write_bytes",
    "write_text",
}


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
        findings = package_security_findings(package)
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

            isolated_command = _isolated_pytest_command(
                sandbox_path,
                python_executable=self.python_executable,
            )
            if isolated_command is None:
                return SandboxResult(
                    passed=False,
                    test_summary="Sandbox execution refused: OS isolation unavailable.",
                    security_findings=[
                        "No supported OS isolation backend is available for generated code."
                    ],
                    resource_usage=_resource_usage(
                        started_at,
                        timeout_seconds=self.timeout_seconds,
                        files_written=len(package.files) + len(package.tests),
                        isolation_backend="unavailable",
                    ),
                )
            command, isolation_backend = isolated_command

            completed = _run_pytest(
                sandbox_path,
                timeout_seconds=self.timeout_seconds,
                command=command,
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
                    isolation_backend=isolation_backend,
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
                isolation_backend=isolation_backend,
            ),
        )


def package_security_findings(package: GeneratedCapabilityPackage) -> list[str]:
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
    local_modules = {
        PurePosixPath(relative_path).parts[0].removesuffix(".py")
        for relative_path in (*package.files.keys(), *package.tests.keys())
        if relative_path.endswith(".py")
    }
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
            if relative_path.endswith(".py"):
                findings.extend(
                    _python_ast_findings(
                        group_name,
                        relative_path,
                        content,
                        local_modules=local_modules,
                    )
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


def _python_ast_findings(
    group_name: str,
    relative_path: str,
    content: str,
    *,
    local_modules: set[str],
) -> list[str]:
    try:
        tree = ast.parse(content, filename=relative_path)
    except SyntaxError as exc:
        return [
            f"{group_name}:{relative_path} has invalid Python syntax at "
            f"line {exc.lineno or 0}."
        ]

    allowed_imports = _SAFE_IMPORT_ROOTS | local_modules
    findings: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".", 1)[0]
                if root not in allowed_imports:
                    findings.append(
                        f"{group_name}:{relative_path} imports non-allowlisted "
                        f"module {alias.name!r}."
                    )
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".", 1)[0]
            if node.level == 0 and root not in allowed_imports:
                findings.append(
                    f"{group_name}:{relative_path} imports non-allowlisted "
                    f"module {node.module!r}."
                )
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in _FORBIDDEN_CALL_NAMES:
                findings.append(
                    f"{group_name}:{relative_path} calls forbidden builtin "
                    f"{node.func.id!r}."
                )
            elif (
                isinstance(node.func, ast.Attribute)
                and node.func.attr in _FORBIDDEN_METHOD_NAMES
            ):
                findings.append(
                    f"{group_name}:{relative_path} calls forbidden method "
                    f"{node.func.attr!r}."
                )
        if isinstance(node, ast.Name) and node.id.startswith("__"):
            findings.append(
                f"{group_name}:{relative_path} accesses forbidden dunder "
                f"name {node.id!r}."
            )
        if isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            findings.append(
                f"{group_name}:{relative_path} accesses forbidden dunder "
                f"attribute {node.attr!r}."
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
    command: list[str],
) -> subprocess.CompletedProcess[str] | subprocess.TimeoutExpired:
    process = subprocess.Popen(
        command,
        cwd=sandbox_path,
        env=_sandbox_env(sandbox_path),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
        return subprocess.CompletedProcess(
            command,
            process.returncode,
            stdout=stdout,
            stderr=stderr,
        )
    except subprocess.TimeoutExpired as exc:
        os.killpg(process.pid, signal.SIGKILL)
        stdout, stderr = process.communicate()
        return subprocess.TimeoutExpired(
            exc.cmd,
            exc.timeout,
            output=stdout,
            stderr=stderr,
        )


def _isolated_pytest_command(
    sandbox_path: Path,
    *,
    python_executable: str,
) -> tuple[list[str], str] | None:
    resolved_python = str(Path(python_executable).expanduser().resolve())
    pytest_command = [
        resolved_python,
        "-m",
        "pytest",
        "-q",
        str(sandbox_path),
    ]
    sandbox_exec = Path("/usr/bin/sandbox-exec")
    if sys.platform == "darwin" and sandbox_exec.exists():
        profile = _macos_sandbox_profile(
            sandbox_path,
            python_executable=python_executable,
        )
        if profile is None:
            return None
        return (
            [str(sandbox_exec), "-p", profile, *pytest_command],
            "macos-seatbelt",
        )

    bubblewrap = shutil.which("bwrap")
    if sys.platform.startswith("linux") and bubblewrap:
        return (
            _linux_bubblewrap_command(
                bubblewrap,
                sandbox_path,
                pytest_command=pytest_command,
                python_executable=python_executable,
            ),
            "linux-bubblewrap",
        )
    return None


def _macos_sandbox_profile(
    sandbox_path: Path,
    *,
    python_executable: str,
) -> str | None:
    executable = Path(python_executable).expanduser().resolve()
    home = Path.home().resolve()
    if executable == home or home in executable.parents:
        return None

    read_roots = {
        Path("/System"),
        Path("/Library/Frameworks"),
        Path(sys.base_prefix).expanduser().resolve(),
        Path(sys.prefix).expanduser().resolve(),
        sandbox_path.resolve(),
    }
    read_rules = "\n".join(
        f"        (subpath {json.dumps(str(path))})"
        for path in sorted(read_roots, key=str)
        if path.exists()
    )
    executable_paths = {
        Path(python_executable).expanduser().absolute(),
        executable,
        Path(sys.base_prefix)
        / "Resources/Python.app/Contents/MacOS/Python",
    }
    executable_rules = "\n".join(
        f"        (literal {json.dumps(str(path))})"
        for path in executable_paths
        if path.exists()
    )
    sandbox_literal = json.dumps(str(sandbox_path.resolve()))
    return "\n".join(
        [
            "(version 1)",
            "(deny default)",
            "(import \"system.sb\")",
            "(allow process-exec",
            executable_rules,
            ")",
            "(allow process-fork)",
            "(allow process-info*)",
            "(allow signal (target self))",
            "(allow sysctl-read)",
            "(deny network*)",
            "(allow file-read-metadata file-test-existence",
            "        (subpath \"/Library\")",
            "        (subpath \"/private/tmp\")",
            "        (subpath \"/private/var/folders\")",
            ")",
            "(allow file-read* file-map-executable file-test-existence",
            read_rules,
            "        (subpath \"/dev\")",
            ")",
            "(allow file-write*",
            f"        (subpath {sandbox_literal})",
            "        (literal \"/dev/null\")",
            ")",
        ]
    )


def _linux_bubblewrap_command(
    bubblewrap: str,
    sandbox_path: Path,
    *,
    pytest_command: list[str],
    python_executable: str,
) -> list[str]:
    command = [
        bubblewrap,
        "--die-with-parent",
        "--unshare-all",
        "--new-session",
        "--proc",
        "/proc",
        "--dev",
        "/dev",
        "--tmpfs",
        "/tmp",
    ]
    read_roots = {
        Path("/bin"),
        Path("/lib"),
        Path("/lib64"),
        Path("/usr"),
        Path(sys.base_prefix).resolve(),
        Path(sys.prefix).resolve(),
        Path(python_executable).resolve().parent.parent,
    }
    for path in sorted(read_roots, key=str):
        if path.exists():
            command.extend(["--ro-bind", str(path), str(path)])
    command.extend(
        [
            "--bind",
            str(sandbox_path),
            str(sandbox_path),
            "--chdir",
            str(sandbox_path),
            *pytest_command,
        ]
    )
    return command


def _sandbox_env(sandbox_path: Path) -> dict[str, str]:
    home = Path.home().resolve()
    safe_python_paths = [str(sandbox_path)]
    for raw_path in sys.path:
        if not raw_path:
            continue
        path = Path(raw_path).expanduser().resolve()
        if path == home or home in path.parents:
            continue
        if path.exists():
            safe_python_paths.append(str(path))
    env = {
        "HOME": str(sandbox_path / "home"),
        "NO_PROXY": "*",
        "PATH": os.environ.get("PATH", ""),
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "PYTHONPATH": os.pathsep.join(dict.fromkeys(safe_python_paths)),
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
    isolation_backend: str = "none",
) -> dict[str, float | int | bool | str | None]:
    return {
        "seconds": round(time.monotonic() - started_at, 4),
        "timeout_seconds": timeout_seconds,
        "files_written": files_written,
        "returncode": returncode,
        "timed_out": timed_out,
        "isolation_backend": isolation_backend,
    }


__all__ = [
    "DEFAULT_TIMEOUT_SECONDS",
    "DISALLOWED_PATTERNS",
    "MAX_FILE_BYTES",
    "MAX_PACKAGE_BYTES",
    "MAX_PACKAGE_FILES",
    "package_security_findings",
    "SandboxRunner",
]
