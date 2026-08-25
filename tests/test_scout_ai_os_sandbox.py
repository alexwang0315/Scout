from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from scout.schemas.capability import (
    CapabilityRisk,
    CapabilityRuntime,
    CapabilitySpec,
    GeneratedCapabilityPackage,
)
from scout.services.sandbox_runner import (
    MAX_FILE_BYTES,
    MAX_PACKAGE_FILES,
    SandboxRunner,
    _macos_sandbox_profile,
    _sandbox_env,
)


def make_package(
    *,
    files: dict[str, str] | None = None,
    tests: dict[str, str] | None = None,
    runtime: CapabilityRuntime = CapabilityRuntime.PYTHON,
) -> GeneratedCapabilityPackage:
    return GeneratedCapabilityPackage(
        spec=CapabilitySpec(
            name="generated_json_increment",
            description="Increment an integer value in a JSON-like payload.",
            runtime=runtime,
            risk_level=CapabilityRisk.LOW,
            input_schema={"type": "object"},
            output_schema={"type": "object"},
        ),
        files=files
        if files is not None
        else {
            "implementation.py": (
                "def run(payload):\n"
                "    return {'value': payload['value'] + 1}\n"
            )
        },
        tests=tests
        if tests is not None
        else {
            "test_implementation.py": (
                "from implementation import run\n"
                "\n"
                "def test_run_increments_value():\n"
                "    assert run({'value': 2}) == {'value': 3}\n"
            )
        },
        install_notes="Generated package candidate only.",
    )


def test_sandbox_runner_passes_valid_generated_package() -> None:
    result = SandboxRunner().run(make_package())

    assert result.passed is True
    assert result.security_findings == []
    assert "passed" in result.test_summary
    assert result.resource_usage["files_written"] == 2
    if sys.platform == "darwin":
        assert result.resource_usage["isolation_backend"] == "macos-seatbelt"


def test_sandbox_runner_does_not_install_generated_code() -> None:
    unique_file = "generated_candidate_unique_for_sandbox_test.py"
    repo_target = Path.cwd() / unique_file
    package = make_package(
        files={
            unique_file: (
                "def run(payload):\n"
                "    return payload\n"
            )
        },
        tests={
            "test_unique_candidate.py": (
                "from generated_candidate_unique_for_sandbox_test import run\n"
                "\n"
                "def test_run_returns_payload():\n"
                "    assert run({'ok': True}) == {'ok': True}\n"
            )
        },
    )

    result = SandboxRunner().verify(package)

    assert result.passed is True
    assert not repo_target.exists()


def test_sandbox_runner_fails_invalid_generated_package_tests() -> None:
    result = SandboxRunner().run(
        make_package(
            tests={
                "test_implementation.py": (
                    "from implementation import run\n"
                    "\n"
                    "def test_run_detects_wrong_output():\n"
                    "    assert run({'value': 2}) == {'value': 99}\n"
                )
            }
        )
    )

    assert result.passed is False
    assert "failed" in result.test_summary
    assert result.security_findings == []


def test_sandbox_runner_blocks_disallowed_patterns_before_execution() -> None:
    result = SandboxRunner().run(
        make_package(
            files={
                "implementation.py": (
                    "import subprocess\n"
                    "\n"
                    "def run(payload):\n"
                    "    return payload\n"
                )
            }
        )
    )

    assert result.passed is False
    assert "before execution" in result.test_summary
    assert any("subprocess" in finding for finding in result.security_findings)
    assert result.resource_usage["files_written"] == 0


def test_sandbox_environment_scrubs_parent_secret(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SCOUT_PHASE6_TEST_SECRET", "must-not-cross-boundary")
    env = _sandbox_env(tmp_path)

    assert "SCOUT_PHASE6_TEST_SECRET" not in env
    assert "must-not-cross-boundary" not in str(env)


def test_sandbox_runner_blocks_dynamic_import_before_execution() -> None:
    result = SandboxRunner().run(
        make_package(
            files={
                "implementation.py": (
                    "def run(payload):\n"
                    "    module = __import__('o' + 's')\n"
                    "    values = getattr(module, 'environ')\n"
                    "    return values.get('SCOUT_PHASE6_TEST_' + 'SE' + 'CRET')\n"
                )
            },
            tests={
                "test_implementation.py": (
                    "from implementation import run\n\n"
                    "def test_parent_value_is_not_available():\n"
                    "    assert run({}) is None\n"
                )
            },
        )
    )

    assert result.passed is False
    assert any("__import__" in finding for finding in result.security_findings)
    assert result.resource_usage["files_written"] == 0


def test_sandbox_runner_blocks_ast_obfuscation_and_file_write() -> None:
    result = SandboxRunner().run(
        make_package(
            files={
                "implementation.py": (
                    "from pathlib import Path\n"
                    "from importlib import import_module\n\n"
                    "def run(payload):\n"
                    "    Path('/tmp/scout-escape').write_text('escaped')\n"
                    "    return import_module('sub' + 'process')\n"
                )
            }
        )
    )

    assert result.passed is False
    assert result.resource_usage["files_written"] == 0
    assert any("pathlib" in finding for finding in result.security_findings)
    assert any("importlib" in finding for finding in result.security_findings)
    assert any("write_text" in finding for finding in result.security_findings)


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS Seatbelt proof")
def test_macos_sandbox_profile_blocks_host_file_read(tmp_path: Path) -> None:
    outside_file = tmp_path / "outside-secret.txt"
    outside_file.write_text("must-not-be-readable", encoding="utf-8")
    sandbox_path = tmp_path / "sandbox"
    sandbox_path.mkdir()
    profile = _macos_sandbox_profile(
        sandbox_path,
        python_executable=sys.executable,
    )
    assert profile is not None

    completed = subprocess.run(
        [
            "/usr/bin/sandbox-exec",
            "-p",
            profile,
            str(Path(sys.executable).resolve()),
            "-c",
            f"print(open({str(outside_file)!r}).read())",
        ],
        cwd=sandbox_path,
        env=_sandbox_env(sandbox_path),
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )

    assert completed.returncode != 0
    assert "must-not-be-readable" not in completed.stdout


def test_sandbox_runner_installs_runtime_network_blocker() -> None:
    result = SandboxRunner().run(
        make_package(
            tests={
                "test_network_blocker.py": (
                    "import pytest\n"
                    "import sitecustomize\n\n"
                    "def test_network_is_blocked():\n"
                    "    with pytest.raises(RuntimeError, match='blocks network'):\n"
                    "        sitecustomize._blocked()\n"
                )
            }
        )
    )

    assert result.passed is True


def test_sandbox_runner_blocks_unsafe_paths_before_writing() -> None:
    result = SandboxRunner().run(
        make_package(
            files={"../implementation.py": "def run(payload): return payload\n"}
        )
    )

    assert result.passed is False
    assert any("not a safe path" in finding for finding in result.security_findings)
    assert result.resource_usage["files_written"] == 0


def test_sandbox_runner_blocks_too_many_generated_files() -> None:
    result = SandboxRunner().run(
        make_package(
            files={
                f"module_{index}.py": "def run(payload): return payload\n"
                for index in range(MAX_PACKAGE_FILES + 1)
            }
        )
    )

    assert result.passed is False
    assert any("files; limit" in finding for finding in result.security_findings)
    assert result.resource_usage["files_written"] == 0


def test_sandbox_runner_blocks_oversized_generated_file() -> None:
    result = SandboxRunner().run(
        make_package(
            files={
                "implementation.py": (
                    "PAYLOAD = "
                    + repr("x" * (MAX_FILE_BYTES + 1))
                    + "\n\n"
                    + "def run(payload):\n"
                    + "    return payload\n"
                )
            }
        )
    )

    assert result.passed is False
    assert any("bytes; limit" in finding for finding in result.security_findings)
    assert result.resource_usage["files_written"] == 0


def test_sandbox_runner_times_out_pytest_execution() -> None:
    result = SandboxRunner(timeout_seconds=0.2).run(
        make_package(
            tests={
                "test_implementation.py": (
                    "import time\n"
                    "\n"
                    "def test_timeout():\n"
                    "    time.sleep(5)\n"
                )
            }
        )
    )

    assert result.passed is False
    assert "timed out" in result.test_summary
    assert result.resource_usage["timed_out"] is True
