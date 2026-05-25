from __future__ import annotations

import argparse
import base64
import json
import shlex
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Literal, Sequence

from pydantic import BaseModel, ConfigDict, Field


Classification = Literal["blocking", "major", "minor", "GIS-related"]
Status = Literal["passed", "failed", "skipped"]


class AlphaDeviceSmokeBoundary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    read_only: Literal[True] = True
    ssh_commands_only: Literal[True] = True
    http_methods_allowed: list[Literal["GET"]] = Field(default_factory=lambda: ["GET"])
    local_admin_mutation_performed: Literal[False] = False
    scout_admin_mutation_performed: Literal[False] = False
    gpio_drive_performed: Literal[False] = False
    safety_mutation_performed: Literal[False] = False
    phase2_writeback_performed: Literal[False] = False
    outbound_messages_sent: Literal[False] = False
    token_values_embedded: Literal[False] = False
    raw_payloads_embedded: Literal[False] = False


class AlphaDeviceSmokeCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    check_id: str
    target: Literal["local_9099", "scout_ssh", "scout_9110"]
    status: Status
    classification: Classification
    summary: str
    evidence: dict[str, Any] = Field(default_factory=dict)


class AlphaDeviceSmokeCounts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    passed: int
    failed: int
    skipped: int
    blocking: int
    major: int
    minor: int
    gis_related: int


class AlphaDeviceSmokeResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: Literal["scout_alpha_device_smoke_check"] = (
        "scout_alpha_device_smoke_check"
    )
    status: Literal["passed", "failed"]
    generated_at: float
    local_admin_url: str
    scout_admin_url: str
    scout_host: str
    boundary: AlphaDeviceSmokeBoundary = Field(default_factory=AlphaDeviceSmokeBoundary)
    checks: list[AlphaDeviceSmokeCheck]
    counts: AlphaDeviceSmokeCounts

    def to_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n"


@dataclass(frozen=True)
class HttpResponse:
    status_code: int
    body: str


HttpGet = Callable[[str, float], HttpResponse]
SshRun = Callable[[str, str, float], subprocess.CompletedProcess[str]]


CHILAI_PROJECT_PATH = "/admin/pretrip/projects/chilai_nanhua_day1"
CHILAI_ROUTE_POINT_COUNT = 6909
CHILAI_ROUTE_BOUNDS = {
    "min_lat": 23.872665725648403,
    "min_lon": 121.17726685479283,
    "max_lat": 24.053969560191035,
    "max_lon": 121.281699500978,
}
CHILAI_REQUIRED_MAP_LAYERS = {
    "imagery",
    "osm",
    "terrain",
    "corridors",
    "hazards",
    "route",
    "reference-tracks",
    "retreat",
    "segments",
    "checkpoints",
    "pois",
    "route-notes",
    "weather-api",
}


def run_alpha_device_smoke_check(
    *,
    local_admin_url: str = "http://127.0.0.1:9099",
    scout_admin_url: str = "http://scout.local:9110",
    scout_host: str = "scout",
    timeout_seconds: float = 5.0,
    skip_local: bool = False,
    skip_scout: bool = False,
    http_get: HttpGet | None = None,
    ssh_run: SshRun | None = None,
) -> AlphaDeviceSmokeResult:
    http_get = http_get or _http_get
    ssh_run = ssh_run or _ssh_run
    checks: list[AlphaDeviceSmokeCheck] = []

    if skip_local:
        checks.append(_skipped("local_admin_health", "local_9099", "major", "local 9099 check skipped"))
        checks.append(_skipped("local_hardware_context", "local_9099", "major", "local hardware context check skipped"))
        checks.append(_skipped("local_pretrip_chilai_project", "local_9099", "major", "local Chilai pretrip project check skipped"))
    else:
        checks.append(
            _check_http_json(
                "local_admin_health",
                "local_9099",
                f"{local_admin_url.rstrip('/')}/health",
                timeout_seconds,
                http_get,
                _validate_admin_health,
                "local 9099 health exposes phase4 admin runtime",
            )
        )
        checks.append(
            _check_http_json(
                "local_hardware_context",
                "local_9099",
                f"{local_admin_url.rstrip('/')}/admin/hardware-readiness/context",
                timeout_seconds,
                http_get,
                _validate_hardware_context,
                "local 9099 hardware context exposes GPIO Lab Mode gate",
            )
        )
        checks.append(
            _check_http_json(
                "local_pretrip_chilai_project",
                "local_9099",
                f"{local_admin_url.rstrip('/')}{CHILAI_PROJECT_PATH}",
                timeout_seconds,
                http_get,
                _validate_chilai_pretrip_project,
                "local 9099 Chilai pretrip project exposes alpha map route package",
            )
        )

    if skip_scout:
        checks.append(_skipped("scout_host_reachable", "scout_ssh", "blocking", "Scout SSH check skipped"))
        checks.append(_skipped("scout_admin_container", "scout_ssh", "major", "Scout admin container check skipped"))
        checks.append(_skipped("scout_admin_health", "scout_9110", "major", "Scout 9110 health check skipped"))
        checks.append(_skipped("scout_hardware_context", "scout_9110", "major", "Scout 9110 hardware context check skipped"))
        checks.append(_skipped("scout_debug_page", "scout_9110", "major", "Scout 9110 debug page check skipped"))
        checks.append(_skipped("scout_pretrip_chilai_project", "scout_9110", "major", "Scout 9110 Chilai pretrip project check skipped"))
    else:
        checks.append(_check_scout_host(scout_host, timeout_seconds, ssh_run))
        checks.append(_check_scout_admin_container(scout_host, timeout_seconds, ssh_run))
        checks.append(
            _check_remote_admin_json(
                "scout_admin_health",
                "/health",
                scout_host,
                timeout_seconds,
                ssh_run,
                _validate_admin_health,
                "Scout 9110 health exposes phase4 admin runtime",
            )
        )
        checks.append(
            _check_remote_admin_json(
                "scout_hardware_context",
                "/admin/hardware-readiness/context",
                scout_host,
                timeout_seconds,
                ssh_run,
                _validate_hardware_context,
                "Scout 9110 hardware context exposes GPIO Lab Mode gate",
            )
        )
        checks.append(_check_remote_debug_page(scout_host, timeout_seconds, ssh_run))
        checks.append(
            _check_remote_admin_json(
                "scout_pretrip_chilai_project",
                CHILAI_PROJECT_PATH,
                scout_host,
                timeout_seconds,
                ssh_run,
                _validate_chilai_pretrip_project,
                "Scout 9110 Chilai pretrip project exposes alpha map route package",
            )
        )

    return _result(
        checks=checks,
        local_admin_url=local_admin_url.rstrip("/"),
        scout_admin_url=scout_admin_url.rstrip("/"),
        scout_host=scout_host,
    )


def _check_http_json(
    check_id: str,
    target: Literal["local_9099", "scout_ssh", "scout_9110"],
    url: str,
    timeout_seconds: float,
    http_get: HttpGet,
    validator: Callable[[dict[str, Any]], list[str]],
    passed_summary: str,
) -> AlphaDeviceSmokeCheck:
    try:
        response = http_get(url, timeout_seconds)
        payload = json.loads(response.body)
    except Exception as exc:
        return _failed(check_id, target, "major", f"GET {url} failed", {"error": str(exc)})
    missing = validator(payload)
    return AlphaDeviceSmokeCheck(
        check_id=check_id,
        target=target,
        status="failed" if missing or response.status_code != 200 else "passed",
        classification="major",
        summary=passed_summary if not missing and response.status_code == 200 else "admin JSON contract mismatch",
        evidence={
            "status_code": response.status_code,
            "missing": missing,
            "keys": sorted(payload.keys())[:20],
        },
    )


def _check_scout_host(
    scout_host: str,
    timeout_seconds: float,
    ssh_run: SshRun,
) -> AlphaDeviceSmokeCheck:
    command = (
        "set -eu; "
        "hostname; "
        "uname -m; "
        "(command -v vcgencmd >/dev/null 2>&1 && vcgencmd measure_temp || true); "
        "df -h / | tail -1"
    )
    completed = ssh_run(scout_host, command, timeout_seconds)
    if completed.returncode != 0:
        return _failed(
            "scout_host_reachable",
            "scout_ssh",
            "blocking",
            "Scout host SSH read-only probe failed",
            _completed_evidence(completed),
        )
    lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    return AlphaDeviceSmokeCheck(
        check_id="scout_host_reachable",
        target="scout_ssh",
        status="passed",
        classification="blocking",
        summary="Scout host is reachable over SSH",
        evidence={
            "hostname": lines[0] if lines else None,
            "arch": lines[1] if len(lines) > 1 else None,
            "temperature": next((line for line in lines if line.startswith("temp=")), None),
            "root_df": lines[-1] if lines else None,
        },
    )


def _check_scout_admin_container(
    scout_host: str,
    timeout_seconds: float,
    ssh_run: SshRun,
) -> AlphaDeviceSmokeCheck:
    command = (
        "set -eu; "
        "docker inspect -f '{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{else}}no-health{{end}}' scout-pi-phase4-admin; "
        "docker port scout-pi-phase4-admin 9099/tcp || true"
    )
    completed = ssh_run(scout_host, command, timeout_seconds)
    if completed.returncode != 0:
        return _failed(
            "scout_admin_container",
            "scout_ssh",
            "major",
            "Scout admin container is not inspectable",
            _completed_evidence(completed),
        )
    output = completed.stdout.strip()
    ok = "running healthy" in output and "9110" in output
    return AlphaDeviceSmokeCheck(
        check_id="scout_admin_container",
        target="scout_ssh",
        status="passed" if ok else "failed",
        classification="major",
        summary="Scout admin container is healthy and maps 9110"
        if ok
        else "Scout admin container health or port mapping mismatch",
        evidence={"output": output},
    )


def _check_remote_admin_json(
    check_id: str,
    path: str,
    scout_host: str,
    timeout_seconds: float,
    ssh_run: SshRun,
    validator: Callable[[dict[str, Any]], list[str]],
    passed_summary: str,
) -> AlphaDeviceSmokeCheck:
    completed = ssh_run(scout_host, _remote_admin_json_command(path), timeout_seconds)
    if completed.returncode != 0:
        return _failed(
            check_id,
            "scout_9110",
            "major",
            f"Scout admin GET {path} failed",
            _completed_evidence(completed),
        )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        return _failed(
            check_id,
            "scout_9110",
            "major",
            f"Scout admin GET {path} did not return JSON",
            {"error": str(exc), "stdout": completed.stdout[:500]},
        )
    body = payload.get("json") if isinstance(payload.get("json"), dict) else {}
    missing = validator(body) if payload.get("status_code") == 200 else ["non_200_status"]
    return AlphaDeviceSmokeCheck(
        check_id=check_id,
        target="scout_9110",
        status="failed" if missing else "passed",
        classification="major",
        summary=passed_summary if not missing else f"Scout admin GET {path} contract mismatch",
        evidence={
            "status_code": payload.get("status_code"),
            "missing": missing,
            "keys": sorted(body.keys())[:20],
            "token_values_embedded": False,
        },
    )


def _check_remote_debug_page(
    scout_host: str,
    timeout_seconds: float,
    ssh_run: SshRun,
) -> AlphaDeviceSmokeCheck:
    completed = ssh_run(
        scout_host,
        _remote_admin_text_command("/admin/debug"),
        timeout_seconds,
    )
    if completed.returncode != 0:
        return _failed(
            "scout_debug_page",
            "scout_9110",
            "major",
            "Scout admin debug page request failed",
            _completed_evidence(completed),
        )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        return _failed(
            "scout_debug_page",
            "scout_9110",
            "major",
            "Scout admin debug page response was not JSON-wrapped",
            {"error": str(exc), "stdout": completed.stdout[:500]},
        )
    text = str(payload.get("text_excerpt", ""))
    missing = [
        label
        for label, present in {
            "HTTP 200": payload.get("status_code") == 200,
            "hardware tab": 'id="tab-hardware"' in text,
            "hardware context fetch": "/admin/hardware-readiness/context" in text,
            "gpioset gate": "gpioset_enabled" in text,
        }.items()
        if not present
    ]
    return AlphaDeviceSmokeCheck(
        check_id="scout_debug_page",
        target="scout_9110",
        status="failed" if missing else "passed",
        classification="major",
        summary="Scout 9110 /admin/debug exposes hardware tab and GPIO gate"
        if not missing
        else "Scout 9110 /admin/debug is missing hardware alpha UI markers",
        evidence={
            "status_code": payload.get("status_code"),
            "missing": missing,
            "token_values_embedded": False,
        },
    )


def _validate_admin_health(payload: dict[str, Any]) -> list[str]:
    routes = payload.get("routes") if isinstance(payload.get("routes"), dict) else {}
    boundaries = payload.get("boundaries") if isinstance(payload.get("boundaries"), dict) else {}
    safety_disabled = (
        payload.get("safety_enabled") is False
        or boundaries.get("safety_enabled") is False
        or (
            boundaries.get("phase1_field_runtime_started") is False
            and boundaries.get("safety_api_mutation_allowed") is False
        )
    )
    expected = {
        "status_ok": payload.get("status") == "ok",
        "profile": payload.get("runtime_profile") == "pi-phase4-admin-preview",
        "hardware_route": routes.get("hardware_readiness") == "/admin/hardware-readiness",
        "hardware_context_route": routes.get("hardware_readiness_context") == "/admin/hardware-readiness/context",
        "safety_disabled": safety_disabled,
        "hardware_control_blocked": boundaries.get("hardware_control_allowed") is False,
    }
    return [name for name, present in expected.items() if not present]


def _validate_hardware_context(payload: dict[str, Any]) -> list[str]:
    interfaces = {
        item.get("interface_ref"): item
        for item in payload.get("interface_inventory", [])
        if isinstance(item, dict)
    }
    gpio = interfaces.get("gpio.bank0.controls") or {}
    boundary = payload.get("boundary") if isinstance(payload.get("boundary"), dict) else {}
    gpio_boundary = gpio.get("boundary") if isinstance(gpio.get("boundary"), dict) else {}
    observed_lines = gpio.get("observed_lines") if isinstance(gpio.get("observed_lines"), list) else []
    expected = {
        "surface": payload.get("surface") == "hardware_readiness",
        "read_only": payload.get("read_only") is True,
        "hardware_control_blocked": boundary.get("hardware_control_allowed") is False,
        "lab_policy_allowed": boundary.get("gpio_lab_mode_drive_policy_allowed") is True,
        "drive_impl_disabled": boundary.get("gpio_drive_implementation_enabled") is False,
        "gpio_interface": bool(gpio),
        "gpio_lines_28": len(observed_lines) == 28,
        "gpioset_disabled": gpio_boundary.get("gpioset_command_enabled") is False,
        "wiring_unconfirmed": gpio_boundary.get("wiring_manifest_confirmed") is False,
        "write_not_performed": gpio_boundary.get("write_performed_by_probe") is False,
    }
    return [name for name, present in expected.items() if not present]


def _validate_chilai_pretrip_project(payload: dict[str, Any]) -> list[str]:
    route = payload.get("route") if isinstance(payload.get("route"), dict) else {}
    bounds = route.get("bounds") if isinstance(route.get("bounds"), dict) else {}
    layer_ids = {
        layer.get("id") or layer.get("layer_id")
        for layer in payload.get("map_layers", [])
        if isinstance(layer, dict)
    }
    layer_preparation = (
        payload.get("layer_preparation")
        if isinstance(payload.get("layer_preparation"), dict)
        else {}
    )
    counts = (
        layer_preparation.get("counts")
        if isinstance(layer_preparation.get("counts"), dict)
        else {}
    )
    reference_tracks = payload.get("reference_tracks")
    expected = {
        "project_id": payload.get("project_id") == "chilai_nanhua_day1",
        "route_point_count": route.get("point_count") == CHILAI_ROUTE_POINT_COUNT,
        "route_bounds": _bounds_match(bounds, CHILAI_ROUTE_BOUNDS),
        "map_layers": CHILAI_REQUIRED_MAP_LAYERS.issubset(layer_ids),
        "reference_tracks": _has_reference_track_summary(reference_tracks),
        "layer_preparation_status": layer_preparation.get("status")
        in {"ready", "ready_with_warnings"},
        "layer_preparation_ready": counts.get("ready_layer_count") == 9,
        "layer_preparation_unblocked": counts.get("blocker_count") == 0
        and counts.get("blocked_layer_count") == 0,
    }
    return [name for name, present in expected.items() if not present]


def _has_reference_track_summary(value: Any) -> bool:
    if isinstance(value, dict):
        return int(value.get("reference_track_count") or 0) > 0 or bool(
            value.get("golden_route")
        )
    return isinstance(value, list) and len(value) > 0


def _bounds_match(actual: dict[str, Any], expected: dict[str, float]) -> bool:
    for key, expected_value in expected.items():
        try:
            actual_value = float(actual.get(key))
        except (TypeError, ValueError):
            return False
        if abs(actual_value - expected_value) > 0.0000001:
            return False
    return True


def _remote_admin_json_command(path: str) -> str:
    return _remote_admin_command(path, parse_json=True)


def _remote_admin_text_command(path: str) -> str:
    return _remote_admin_command(path, parse_json=False)


def _remote_admin_command(path: str, *, parse_json: bool) -> str:
    quoted_path = shlex.quote(path)
    parser = 'json.loads(body) if body.strip().startswith(("{", "[")) else None'
    if not parse_json:
        parser = "None"
    return f"""docker exec scout-pi-phase4-admin sh -lc 'SCOUT_CHECK_PATH={quoted_path} python - <<\"PY\"
import base64, json, os, urllib.error, urllib.request
path = os.environ["SCOUT_CHECK_PATH"]
token = open("/data/scout/admin/secrets/phase4-admin-token", encoding="utf-8").read().strip()
cred = base64.b64encode(("scout-admin:" + token).encode()).decode()
request = urllib.request.Request("http://127.0.0.1:9099" + path, headers={{"Authorization": "Basic " + cred}})
try:
    response = urllib.request.urlopen(request, timeout=3)
    status = response.status
    body = response.read().decode("utf-8", errors="replace")
except urllib.error.HTTPError as exc:
    status = exc.code
    body = exc.read().decode("utf-8", errors="replace")
parsed = {parser}
print(json.dumps({{"status_code": status, "json": parsed, "text_excerpt": body[:120000], "token_values_embedded": False}}, sort_keys=True))
PY'"""


def _http_get(url: str, timeout_seconds: float) -> HttpResponse:
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            return HttpResponse(
                status_code=response.status,
                body=response.read().decode("utf-8", errors="replace"),
            )
    except urllib.error.HTTPError as exc:
        return HttpResponse(
            status_code=exc.code,
            body=exc.read().decode("utf-8", errors="replace"),
        )


def _ssh_run(
    scout_host: str,
    command: str,
    timeout_seconds: float,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["ssh", scout_host, command],
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )


def _result(
    *,
    checks: list[AlphaDeviceSmokeCheck],
    local_admin_url: str,
    scout_admin_url: str,
    scout_host: str,
) -> AlphaDeviceSmokeResult:
    failed = [check for check in checks if check.status == "failed"]
    counts = AlphaDeviceSmokeCounts(
        passed=sum(1 for check in checks if check.status == "passed"),
        failed=len(failed),
        skipped=sum(1 for check in checks if check.status == "skipped"),
        blocking=sum(1 for check in failed if check.classification == "blocking"),
        major=sum(1 for check in failed if check.classification == "major"),
        minor=sum(1 for check in failed if check.classification == "minor"),
        gis_related=sum(1 for check in failed if check.classification == "GIS-related"),
    )
    return AlphaDeviceSmokeResult(
        status="failed" if failed else "passed",
        generated_at=time.time(),
        local_admin_url=local_admin_url,
        scout_admin_url=scout_admin_url,
        scout_host=scout_host,
        checks=checks,
        counts=counts,
    )


def _completed_evidence(completed: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    return {
        "returncode": completed.returncode,
        "stdout": completed.stdout.strip()[:1000],
        "stderr": completed.stderr.strip()[:1000],
    }


def _failed(
    check_id: str,
    target: Literal["local_9099", "scout_ssh", "scout_9110"],
    classification: Classification,
    summary: str,
    evidence: dict[str, Any],
) -> AlphaDeviceSmokeCheck:
    return AlphaDeviceSmokeCheck(
        check_id=check_id,
        target=target,
        status="failed",
        classification=classification,
        summary=summary,
        evidence=evidence,
    )


def _skipped(
    check_id: str,
    target: Literal["local_9099", "scout_ssh", "scout_9110"],
    classification: Classification,
    summary: str,
) -> AlphaDeviceSmokeCheck:
    return AlphaDeviceSmokeCheck(
        check_id=check_id,
        target=target,
        status="skipped",
        classification=classification,
        summary=summary,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run a read-only Scout alpha device baseline smoke check."
    )
    parser.add_argument("--local-admin-url", default="http://127.0.0.1:9099")
    parser.add_argument("--scout-admin-url", default="http://scout.local:9110")
    parser.add_argument("--scout-host", default="scout")
    parser.add_argument("--timeout-seconds", type=float, default=5.0)
    parser.add_argument("--skip-local", action="store_true")
    parser.add_argument("--skip-scout", action="store_true")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)

    result = run_alpha_device_smoke_check(
        local_admin_url=args.local_admin_url,
        scout_admin_url=args.scout_admin_url,
        scout_host=args.scout_host,
        timeout_seconds=args.timeout_seconds,
        skip_local=args.skip_local,
        skip_scout=args.skip_scout,
    )
    output = (
        result.to_json()
        if args.pretty
        else json.dumps(result.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
        + "\n"
    )
    sys.stdout.write(output)
    return 0 if result.status == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
