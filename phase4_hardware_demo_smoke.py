from __future__ import annotations

import argparse
import base64
import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping


DEFAULT_ADMIN_BASE_URL = "http://scout.local:9110"
DEFAULT_RUNTIME_BASE_URL = "http://scout.local:9099"
DEFAULT_ADMIN_BASIC_USERNAME = "scout-admin"
DEFAULT_ADMIN_TOKEN_ENV = "SCOUT_ADMIN_ACCESS_TOKEN"
DEFAULT_TIMEOUT_SECONDS = 3.0

UrlOpen = Callable[..., Any]


@dataclass(frozen=True)
class EndpointSpec:
    endpoint_id: str
    base: str
    path: str
    expected_content: str
    expected_status_values: tuple[str, ...] = ("ok",)


ADMIN_ENDPOINTS: tuple[EndpointSpec, ...] = (
    EndpointSpec("admin_health", "admin", "/health", "json", ("ok",)),
    EndpointSpec("pretrip_admin", "admin", "/admin/pretrip", "html", ()),
    EndpointSpec(
        "pretrip_project",
        "admin",
        "/admin/pretrip/projects/chilai_nanhua_day1",
        "json",
        (),
    ),
    EndpointSpec("assistant_status", "admin", "/assistant/status", "json", ()),
    EndpointSpec(
        "admin_preview_status",
        "admin",
        "/phase4/admin-preview/status",
        "json",
        ("ready",),
    ),
)
RUNTIME_ENDPOINTS: tuple[EndpointSpec, ...] = (
    EndpointSpec("runtime_health", "runtime", "/health", "json", ("ok",)),
)


def build_phase4_hardware_demo_smoke(
    *,
    admin_base_url: str = DEFAULT_ADMIN_BASE_URL,
    runtime_base_url: str = DEFAULT_RUNTIME_BASE_URL,
    admin_auth_token: str | None = None,
    admin_basic_username: str = DEFAULT_ADMIN_BASIC_USERNAME,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    urlopen: UrlOpen = urllib.request.urlopen,
) -> dict[str, Any]:
    admin_base = _normalize_base_url(admin_base_url)
    runtime_base = _normalize_base_url(runtime_base_url)
    admin_auth_header = _build_basic_auth_header(
        username=admin_basic_username,
        token=admin_auth_token,
    )
    endpoints = [
        _check_endpoint(
            spec,
            base_url=admin_base if spec.base == "admin" else runtime_base,
            auth_header=admin_auth_header if spec.base == "admin" else None,
            timeout_seconds=timeout_seconds,
            urlopen=urlopen,
        )
        for spec in (*ADMIN_ENDPOINTS, *RUNTIME_ENDPOINTS)
    ]
    failed = [endpoint for endpoint in endpoints if endpoint["status"] != "passed"]
    return {
        "artifact_kind": "phase4_hardware_demo_smoke_result",
        "status": "failed" if failed else "passed",
        "admin_base_url": admin_base,
        "runtime_base_url": runtime_base,
        "boundaries": {
            "read_only_http_get_only": True,
            "phase1_runtime_mutation_allowed": False,
            "phase2_writeback_allowed": False,
            "assistant_expected_read_only": True,
            "repo_fixture_write_allowed": False,
            "outbound_messages_allowed": False,
            "hardware_control_allowed": False,
            "secrets_in_output_allowed": False,
            "response_body_echo_allowed": False,
            "admin_auth_supported": True,
            "runtime_auth_header_sent": False,
        },
        "auth": {
            "admin_auth_header_sent": bool(admin_auth_header),
            "admin_auth_scheme": "basic" if admin_auth_header else None,
            "admin_basic_username": admin_basic_username,
            "token_value_exposed": False,
        },
        "endpoint_statuses": endpoints,
        "counts": {
            "passed": len(endpoints) - len(failed),
            "failed": len(failed),
            "endpoint_count": len(endpoints),
        },
    }


def _check_endpoint(
    spec: EndpointSpec,
    *,
    base_url: str,
    auth_header: str | None,
    timeout_seconds: float,
    urlopen: UrlOpen,
) -> dict[str, Any]:
    url = f"{base_url}{spec.path}"
    headers = {
        "Accept": "application/json,text/html;q=0.9,*/*;q=0.1",
        "User-Agent": "scout-phase4-hardware-demo-smoke/1",
    }
    if auth_header:
        headers["Authorization"] = auth_header
    request = urllib.request.Request(
        url,
        headers=headers,
        method="GET",
    )
    result: dict[str, Any] = {
        "endpoint_id": spec.endpoint_id,
        "base": spec.base,
        "method": "GET",
        "path": spec.path,
        "url": url,
        "status": "failed",
        "http_status": None,
        "content_type": None,
        "expected_content": spec.expected_content,
        "auth_header_sent": bool(auth_header),
        "summary": "not checked",
        "missing": [],
    }
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            result["http_status"] = int(response.getcode())
            result["content_type"] = response.headers.get("content-type", "")
            raw = response.read()
    except urllib.error.HTTPError as exc:
        result["http_status"] = int(exc.code)
        result["summary"] = f"http error {exc.code}"
        result["missing"] = [f"{spec.endpoint_id}:http_error:{exc.code}"]
        return result
    except (OSError, urllib.error.URLError, TimeoutError) as exc:
        result["summary"] = f"request failed: {type(exc).__name__}"
        result["missing"] = [f"{spec.endpoint_id}:request_failed:{type(exc).__name__}"]
        return result

    missing = _http_missing(spec, result)
    if spec.expected_content == "json":
        parsed, parse_missing = _parse_json_payload(spec, raw)
        result["payload_summary"] = parsed
        missing.extend(parse_missing)
    else:
        text = raw.decode("utf-8", errors="replace")
        result["payload_summary"] = {
            "html_present": bool(text.strip()),
            "contains_pretrip_project_path": (
                "/admin/pretrip/projects/chilai_nanhua_day1" in text
                or "/admin/pretrip/projects/${PROJECT_ID}" in text
            ),
        }
        if not result["payload_summary"]["html_present"]:
            missing.append(f"{spec.endpoint_id}:empty_html")

    result["missing"] = missing
    result["status"] = "passed" if not missing else "failed"
    result["summary"] = "endpoint passed smoke check" if not missing else "endpoint failed smoke check"
    return result


def _http_missing(spec: EndpointSpec, result: dict[str, Any]) -> list[str]:
    status = result["http_status"]
    if not isinstance(status, int) or not 200 <= status < 300:
        return [f"{spec.endpoint_id}:http_status_not_2xx"]
    return []


def _parse_json_payload(spec: EndpointSpec, raw: bytes) -> tuple[dict[str, Any], list[str]]:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}, [f"{spec.endpoint_id}:json_unparseable"]
    if not isinstance(payload, dict):
        return {}, [f"{spec.endpoint_id}:json_not_object"]

    summary = _safe_payload_summary(payload)
    missing: list[str] = []
    if spec.expected_status_values:
        status = payload.get("status")
        if status not in spec.expected_status_values:
            expected = "|".join(spec.expected_status_values)
            missing.append(f"{spec.endpoint_id}:status_not_{expected}")
    if spec.endpoint_id == "assistant_status":
        missing.extend(_assistant_status_missing(payload))
    if spec.endpoint_id == "admin_preview_status":
        boundaries = payload.get("boundaries")
        if not isinstance(boundaries, dict) or boundaries.get("hardware_control_allowed") is not False:
            missing.append("admin_preview_status:hardware_control_boundary_missing")
        if not isinstance(boundaries, dict) or boundaries.get("phase1_field_runtime_started") is not False:
            missing.append("admin_preview_status:phase1_runtime_boundary_missing")
    return summary, missing


def _safe_payload_summary(payload: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key in (
        "artifact_kind",
        "status",
        "runtime_profile",
        "provider",
        "provider_class",
        "read_only",
        "token_values_exposed",
        "readiness_starts_local_model",
        "status_model_switch_allowed",
    ):
        if key in payload:
            summary[key] = payload[key]
    if isinstance(payload.get("boundaries"), dict):
        summary["boundaries"] = {
            key: payload["boundaries"].get(key)
            for key in (
                "phase1_field_runtime_started",
                "phase1_safety_decision_mutation_allowed",
                "phase2_writeback_allowed",
                "outbound_messages_allowed",
                "hardware_control_allowed",
                "assistant_read_only",
            )
            if key in payload["boundaries"]
        }
    if isinstance(payload.get("auth"), dict):
        summary["auth"] = {
            key: payload["auth"].get(key)
            for key in (
                "required",
                "token_configured",
                "token_source",
                "token_value_exposed",
                "misconfigured",
            )
            if key in payload["auth"]
        }
    if "project_id" in payload:
        summary["project_id"] = payload["project_id"]
    return summary


def _assistant_status_missing(payload: dict[str, Any]) -> list[str]:
    expected = {
        "read_only": True,
        "provider": "mock",
        "token_values_exposed": False,
        "readiness_starts_local_model": False,
        "status_model_switch_allowed": False,
    }
    missing: list[str] = []
    for key, value in expected.items():
        if payload.get(key) != value:
            missing.append(f"assistant_status:{key}!={value}")
    return missing


def _normalize_base_url(value: str) -> str:
    normalized = value.strip().rstrip("/")
    if not normalized:
        raise ValueError("base URL must not be empty")
    if "@" in normalized:
        raise ValueError("base URL must not include credentials")
    return normalized


def _build_basic_auth_header(*, username: str, token: str | None) -> str | None:
    clean_token = token.strip() if isinstance(token, str) else ""
    if not clean_token:
        return None
    clean_username = username.strip() or DEFAULT_ADMIN_BASIC_USERNAME
    raw = f"{clean_username}:{clean_token}".encode("utf-8")
    return "Basic " + base64.b64encode(raw).decode("ascii")


def _resolve_admin_auth_token(
    *,
    token_env: str = DEFAULT_ADMIN_TOKEN_ENV,
    token_file: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> str | None:
    env = os.environ if environ is None else environ
    if token_file:
        try:
            token = Path(token_file).expanduser().read_text(encoding="utf-8").strip()
        except OSError:
            token = ""
        if token:
            return token
    return env.get(token_env, "").strip() or None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Smoke-check an already deployed Scout Phase 4 admin preview and "
            "runtime health endpoint."
        )
    )
    parser.add_argument("--admin-base-url", default=DEFAULT_ADMIN_BASE_URL)
    parser.add_argument("--runtime-base-url", default=DEFAULT_RUNTIME_BASE_URL)
    parser.add_argument("--admin-basic-username", default=DEFAULT_ADMIN_BASIC_USERNAME)
    parser.add_argument("--admin-token-env", default=DEFAULT_ADMIN_TOKEN_ENV)
    parser.add_argument("--admin-token-file")
    parser.add_argument("--timeout-seconds", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--pretty", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    admin_auth_token = _resolve_admin_auth_token(
        token_env=args.admin_token_env,
        token_file=args.admin_token_file,
    )
    result = build_phase4_hardware_demo_smoke(
        admin_base_url=args.admin_base_url,
        runtime_base_url=args.runtime_base_url,
        admin_auth_token=admin_auth_token,
        admin_basic_username=args.admin_basic_username,
        timeout_seconds=args.timeout_seconds,
    )
    print(json.dumps(result, ensure_ascii=True, indent=2 if args.pretty else None))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
