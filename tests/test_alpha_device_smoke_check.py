from __future__ import annotations

import json
import subprocess

import alpha_device_smoke_check as smoke


def _health() -> dict:
    return {
        "status": "ok",
        "runtime_profile": "pi-phase4-admin-preview",
        "routes": {
            "hardware_readiness": "/admin/hardware-readiness",
            "hardware_readiness_context": "/admin/hardware-readiness/context",
        },
        "boundaries": {
            "phase1_field_runtime_started": False,
            "safety_api_mutation_allowed": False,
            "hardware_control_allowed": False,
        },
    }


def _hardware_context() -> dict:
    return {
        "surface": "hardware_readiness",
        "read_only": True,
        "boundary": {
            "hardware_control_allowed": False,
            "gpio_lab_mode_drive_policy_allowed": True,
            "gpio_drive_implementation_enabled": False,
        },
        "interface_inventory": [
            {
                "interface_ref": "gpio.bank0.controls",
                "observed_lines": [
                    {"gpio": index, "manual_read_allowed": True, "manual_write_allowed": True}
                    for index in range(28)
                ],
                "boundary": {
                    "gpioset_command_enabled": False,
                    "wiring_manifest_confirmed": False,
                    "write_performed_by_probe": False,
                },
            }
        ],
    }


def _chilai_project(point_count: int = smoke.CHILAI_ROUTE_POINT_COUNT) -> dict:
    return {
        "project_id": "chilai_nanhua_day1",
        "route": {
            "point_count": point_count,
            "bounds": smoke.CHILAI_ROUTE_BOUNDS,
        },
        "reference_tracks": {
            "source_id": "reference_tracks.chilai_nanhua_day1",
            "reference_track_count": 23,
            "golden_route": {"point_count": point_count},
        },
        "map_layers": [
            {"layer_id": layer_id}
            for layer_id in sorted(smoke.CHILAI_REQUIRED_MAP_LAYERS)
        ],
        "layer_preparation": {
            "status": "ready_with_warnings",
            "counts": {
                "blocked_layer_count": 0,
                "blocker_count": 0,
                "layer_count": 9,
                "missing_layer_count": 0,
                "ready_layer_count": 9,
                "warning_count": 2,
            },
        },
    }


def test_alpha_device_smoke_check_passes_with_local_and_scout_contracts() -> None:
    def fake_http_get(url: str, timeout_seconds: float) -> smoke.HttpResponse:
        if url.endswith("/health"):
            return smoke.HttpResponse(200, json.dumps(_health()))
        if url.endswith("/admin/hardware-readiness/context"):
            return smoke.HttpResponse(200, json.dumps(_hardware_context()))
        if url.endswith(smoke.CHILAI_PROJECT_PATH):
            return smoke.HttpResponse(200, json.dumps(_chilai_project()))
        raise AssertionError(url)

    def fake_ssh_run(
        scout_host: str,
        command: str,
        timeout_seconds: float,
    ) -> subprocess.CompletedProcess[str]:
        if "hostname" in command:
            return subprocess.CompletedProcess(
                ["ssh"], 0, "scout\naarch64\ntemp=45.2'C\n/dev/sda2 917G 19G 861G 3% /\n", ""
            )
        if "docker inspect" in command:
            return subprocess.CompletedProcess(
                ["ssh"], 0, "running healthy\n0.0.0.0:9110\n", ""
            )
        if 'SCOUT_CHECK_PATH=/health' in command:
            return subprocess.CompletedProcess(
                ["ssh"],
                0,
                json.dumps({"status_code": 200, "json": _health(), "token_values_embedded": False}),
                "",
            )
        if 'SCOUT_CHECK_PATH=/admin/hardware-readiness/context' in command:
            return subprocess.CompletedProcess(
                ["ssh"],
                0,
                json.dumps(
                    {
                        "status_code": 200,
                        "json": _hardware_context(),
                        "token_values_embedded": False,
                    }
                ),
                "",
            )
        if 'SCOUT_CHECK_PATH=/admin/debug' in command:
            return subprocess.CompletedProcess(
                ["ssh"],
                0,
                json.dumps(
                    {
                        "status_code": 200,
                        "json": None,
                        "text_excerpt": (
                            '<div id="tab-hardware"></div>'
                            "/admin/hardware-readiness/context gpioset_enabled"
                        ),
                        "token_values_embedded": False,
                    }
                ),
                "",
            )
        if f"SCOUT_CHECK_PATH={smoke.CHILAI_PROJECT_PATH}" in command:
            return subprocess.CompletedProcess(
                ["ssh"],
                0,
                json.dumps(
                    {
                        "status_code": 200,
                        "json": _chilai_project(),
                        "token_values_embedded": False,
                    }
                ),
                "",
            )
        raise AssertionError(command)

    result = smoke.run_alpha_device_smoke_check(
        http_get=fake_http_get,
        ssh_run=fake_ssh_run,
    )

    assert result.status == "passed"
    assert result.counts.failed == 0
    assert result.counts.passed == 9
    assert result.boundary.gpio_drive_performed is False
    assert result.boundary.safety_mutation_performed is False


def test_alpha_device_smoke_check_classifies_missing_scout_hardware_route_as_major() -> None:
    def fake_http_get(url: str, timeout_seconds: float) -> smoke.HttpResponse:
        if url.endswith("/health"):
            return smoke.HttpResponse(200, json.dumps(_health()))
        if url.endswith(smoke.CHILAI_PROJECT_PATH):
            return smoke.HttpResponse(200, json.dumps(_chilai_project()))
        return smoke.HttpResponse(200, json.dumps(_hardware_context()))

    def fake_ssh_run(
        scout_host: str,
        command: str,
        timeout_seconds: float,
    ) -> subprocess.CompletedProcess[str]:
        if "hostname" in command:
            return subprocess.CompletedProcess(["ssh"], 0, "scout\naarch64\n", "")
        if "docker inspect" in command:
            return subprocess.CompletedProcess(["ssh"], 0, "running healthy\n0.0.0.0:9110\n", "")
        if 'SCOUT_CHECK_PATH=/health' in command:
            return subprocess.CompletedProcess(
                ["ssh"],
                0,
                json.dumps({"status_code": 200, "json": _health(), "token_values_embedded": False}),
                "",
            )
        if 'SCOUT_CHECK_PATH=/admin/hardware-readiness/context' in command:
            return subprocess.CompletedProcess(
                ["ssh"],
                0,
                json.dumps({"status_code": 404, "json": {"detail": "not found"}}),
                "",
            )
        if 'SCOUT_CHECK_PATH=/admin/debug' in command:
            return subprocess.CompletedProcess(
                ["ssh"],
                0,
                json.dumps({"status_code": 200, "text_excerpt": "<html></html>"}),
                "",
            )
        if f"SCOUT_CHECK_PATH={smoke.CHILAI_PROJECT_PATH}" in command:
            return subprocess.CompletedProcess(
                ["ssh"],
                0,
                json.dumps(
                    {
                        "status_code": 200,
                        "json": _chilai_project(),
                        "token_values_embedded": False,
                    }
                ),
                "",
            )
        raise AssertionError(command)

    result = smoke.run_alpha_device_smoke_check(
        http_get=fake_http_get,
        ssh_run=fake_ssh_run,
    )

    failures = {check.check_id: check for check in result.checks if check.status == "failed"}
    assert result.status == "failed"
    assert failures["scout_hardware_context"].classification == "major"
    assert failures["scout_debug_page"].classification == "major"
    assert result.counts.major == 2


def test_alpha_device_smoke_check_classifies_stale_scout_route_as_major() -> None:
    def fake_http_get(url: str, timeout_seconds: float) -> smoke.HttpResponse:
        if url.endswith("/health"):
            return smoke.HttpResponse(200, json.dumps(_health()))
        if url.endswith("/admin/hardware-readiness/context"):
            return smoke.HttpResponse(200, json.dumps(_hardware_context()))
        if url.endswith(smoke.CHILAI_PROJECT_PATH):
            return smoke.HttpResponse(200, json.dumps(_chilai_project()))
        raise AssertionError(url)

    def fake_ssh_run(
        scout_host: str,
        command: str,
        timeout_seconds: float,
    ) -> subprocess.CompletedProcess[str]:
        if "hostname" in command:
            return subprocess.CompletedProcess(["ssh"], 0, "scout\naarch64\n", "")
        if "docker inspect" in command:
            return subprocess.CompletedProcess(["ssh"], 0, "running healthy\n0.0.0.0:9110\n", "")
        if 'SCOUT_CHECK_PATH=/health' in command:
            return subprocess.CompletedProcess(
                ["ssh"],
                0,
                json.dumps({"status_code": 200, "json": _health(), "token_values_embedded": False}),
                "",
            )
        if 'SCOUT_CHECK_PATH=/admin/hardware-readiness/context' in command:
            return subprocess.CompletedProcess(
                ["ssh"],
                0,
                json.dumps(
                    {
                        "status_code": 200,
                        "json": _hardware_context(),
                        "token_values_embedded": False,
                    }
                ),
                "",
            )
        if 'SCOUT_CHECK_PATH=/admin/debug' in command:
            return subprocess.CompletedProcess(
                ["ssh"],
                0,
                json.dumps(
                    {
                        "status_code": 200,
                        "text_excerpt": (
                            '<div id="tab-hardware"></div>'
                            "/admin/hardware-readiness/context gpioset_enabled"
                        ),
                        "token_values_embedded": False,
                    }
                ),
                "",
            )
        if f"SCOUT_CHECK_PATH={smoke.CHILAI_PROJECT_PATH}" in command:
            return subprocess.CompletedProcess(
                ["ssh"],
                0,
                json.dumps(
                    {
                        "status_code": 200,
                        "json": _chilai_project(point_count=2211),
                        "token_values_embedded": False,
                    }
                ),
                "",
            )
        raise AssertionError(command)

    result = smoke.run_alpha_device_smoke_check(
        http_get=fake_http_get,
        ssh_run=fake_ssh_run,
    )

    failures = {check.check_id: check for check in result.checks if check.status == "failed"}
    assert result.status == "failed"
    assert failures["scout_pretrip_chilai_project"].classification == "major"
    assert failures["scout_pretrip_chilai_project"].evidence["missing"] == [
        "route_point_count"
    ]
