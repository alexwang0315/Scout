from __future__ import annotations

import hashlib
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

import scout.services.sandbox_runner as sandbox_runner
from tests.test_scout_ai_os_sandbox import make_package


def _os_probe(sandbox_path: Path, code: str) -> subprocess.CompletedProcess[str]:
    isolated = sandbox_runner._isolated_pytest_command(
        sandbox_path, python_executable=sys.executable
    )
    assert isolated is not None, "This native isolation test requires the platform backend."
    command, backend = isolated
    assert backend == ("macos-seatbelt" if sys.platform == "darwin" else "linux-bubblewrap")
    python_end = command.index("-m")
    # Trusted test harness bypasses the Python network shim to exercise the OS policy.
    return subprocess.run(
        [*command[:python_end], "-I", "-c", code],
        cwd=sandbox_path,
        env=sandbox_runner._sandbox_env(sandbox_path),
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )


def test_generated_pytest_does_not_read_ancestor_configuration(
    tmp_path: Path, monkeypatch
) -> None:
    ancestor = tmp_path / "host-project"
    ancestor.mkdir()
    (ancestor / "pyproject.toml").write_text(
        '[tool.pytest.ini_options]\naddopts = "--host-configuration-must-not-load"\n',
        encoding="utf-8",
    )
    (ancestor / "conftest.py").write_text(
        'raise RuntimeError("ancestor conftest must not load")\n', encoding="utf-8"
    )
    monkeypatch.setattr(tempfile, "tempdir", str(ancestor))

    result = sandbox_runner.SandboxRunner().run(make_package())

    assert result.passed, result.stderr
    assert result.security_findings == []
    assert "1 passed" in result.stdout


def test_generated_pytest_keeps_selected_virtual_environment(
    tmp_path: Path, monkeypatch
) -> None:
    write_blocker = sandbox_runner._write_network_blocker

    def observe_interpreter(sandbox_path: Path) -> None:
        write_blocker(sandbox_path)
        with (sandbox_path / "sitecustomize.py").open("a", encoding="utf-8") as handle:
            handle.write("\nimport sys\nselected_prefix = sys.prefix\n")

    monkeypatch.setattr(sandbox_runner, "_write_network_blocker", observe_interpreter)
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    monkeypatch.setenv("__PYVENV_LAUNCHER__", str(tmp_path / "untrusted-python"))
    monkeypatch.setenv("PYTHONEXECUTABLE", str(tmp_path / "untrusted-python"))
    result = sandbox_runner.SandboxRunner().run(
        make_package(
            tests={
                "test_interpreter.py": (
                    "import sitecustomize\n\n"
                    "def test_selected_environment_is_used():\n"
                    f"    assert sitecustomize.selected_prefix == {sys.prefix!r}\n"
                )
            }
        )
    )

    assert result.passed, result.stdout + result.stderr
    assert "1 passed" in result.stdout


def test_native_isolation_allows_sandbox_io_and_denies_host_file(
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside-probe.txt"
    outside.write_text("scout-outside-read-must-be-denied", encoding="utf-8")
    original_hash = hashlib.sha256(outside.read_bytes()).hexdigest()
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    inside = sandbox / "inside-probe.txt"
    positive = _os_probe(
        sandbox,
        "from pathlib import Path; "
        f"p=Path({str(inside)!r}); p.write_text('inside-io-ok'); print(p.read_text())",
    )
    assert positive.returncode == 0, positive.stderr
    assert positive.stdout.strip() == "inside-io-ok"

    negative = _os_probe(sandbox, f"print(open({str(outside)!r}).read())")

    assert negative.returncode != 0
    assert "scout-outside-read-must-be-denied" not in negative.stdout
    assert any(
        name in negative.stderr for name in ("PermissionError", "FileNotFoundError")
    ), negative.stderr
    denied_write = _os_probe(
        sandbox, f"open({str(outside)!r}, 'r+').write('outside-write-must-be-denied')"
    )
    assert denied_write.returncode != 0
    assert any(
        name in denied_write.stderr for name in ("PermissionError", "FileNotFoundError")
    ), denied_write.stderr
    assert hashlib.sha256(outside.read_bytes()).hexdigest() == original_hash

    # A Linux mount namespace may create a private copy at an unmapped path.
    # Neither a successful private creation nor an OS denial may create a host file.
    new_outside = tmp_path / "outside-new-probe.txt"
    creation = _os_probe(
        sandbox, f"open({str(new_outside)!r}, 'x').write('private-namespace-only')"
    )
    assert not new_outside.exists()
    if creation.returncode != 0:
        assert any(
            name in creation.stderr
            for name in ("PermissionError", "FileNotFoundError", "OSError")
        ), creation.stderr


def test_native_isolation_cannot_reach_parent_loopback_listener(tmp_path: Path) -> None:
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(2)
        port = listener.getsockname()[1]
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            pass
        negative = _os_probe(
            sandbox,
            "import socket; "
            f"s=socket.create_connection(('127.0.0.1', {port}), timeout=1); "
            "print('parent-listener-reached'); s.close()",
        )

    assert negative.returncode != 0
    assert "parent-listener-reached" not in negative.stdout
    assert any(
        name in negative.stderr
        for name in ("PermissionError", "ConnectionRefusedError", "OSError")
    ), negative.stderr
