from __future__ import annotations

import json
import subprocess
import sys
import urllib.error
from pathlib import Path
from typing import Any

import pytest

import phase4_hardware_demo_smoke as smoke


ROOT = Path(__file__).resolve().parents[1]


class FakeResponse:
    def __init__(
        self,
        *,
        status: int = 200,
        payload: dict[str, Any] | None = None,
        body: str | None = None,
        content_type: str = "application/json",
    ) -> None:
        self._status = status
        self._body = (
            json.dumps(payload or {}).encode("utf-8")
            if body is None
            else body.encode("utf-8")
        )
        self.headers = {"content-type": content_type}

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def getcode(self) -> int:
        return self._status

    def read(self) -> bytes:
        return self._body


def fake_urlopen_from(routes: dict[str, FakeResponse]):
    def fake_urlopen(request, timeout):
        assert timeout == 3.0
        assert request.get_method() == "GET"
        url = request.full_url
        if url not in routes:
            raise urllib.error.URLError(f"unexpected URL: {url}")
        return routes[url]

    return fake_urlopen


def recording_urlopen_from(
    routes: dict[str, FakeResponse],
    calls: list[dict[str, str | None]],
):
    def fake_urlopen(request, timeout):
        assert timeout == 3.0
        assert request.get_method() == "GET"
        url = request.full_url
        calls.append(
            {
                "url": url,
                "authorization": request.get_header("Authorization"),
            }
        )
        if url not in routes:
            raise urllib.error.URLError(f"unexpected URL: {url}")
        return routes[url]

    return fake_urlopen


def passing_routes(
    *,
    admin_base: str = "http://scout.local:9110",
    runtime_base: str = "http://scout.local:9099",
) -> dict[str, FakeResponse]:
    return {
        f"{admin_base}/health": FakeResponse(
            payload={
                "status": "ok",
                "artifact_kind": "phase4_admin_runtime_health",
                "runtime_profile": "pi-phase4-admin-preview",
            }
        ),
        f"{admin_base}/admin/pretrip": FakeResponse(
            body='<html><body data-api="/admin/pretrip/projects/chilai_nanhua_day1"></body></html>',
            content_type="text/html",
        ),
        f"{admin_base}/admin/pretrip/projects/chilai_nanhua_day1": FakeResponse(
            payload={"project_id": "chilai_nanhua_day1"}
        ),
        f"{admin_base}/assistant/status": FakeResponse(
            payload={
                "read_only": True,
                "provider": "mock",
                "provider_class": "MockAssistantProvider",
                "token_values_exposed": False,
                "readiness_starts_local_model": False,
                "status_model_switch_allowed": False,
            }
        ),
        f"{admin_base}/phase4/admin-preview/status": FakeResponse(
            payload={
                "status": "ready",
                "artifact_kind": "phase4_admin_hardware_preview_status",
                "boundaries": {
                    "phase1_field_runtime_started": False,
                    "phase1_safety_decision_mutation_allowed": False,
                    "phase2_writeback_allowed": False,
                    "outbound_messages_allowed": False,
                    "hardware_control_allowed": False,
                    "assistant_read_only": True,
                },
            }
        ),
        f"{runtime_base}/health": FakeResponse(
            payload={
                "status": "ok",
                "runtime_profile": "pi-field",
            }
        ),
    }


def test_phase4_hardware_demo_smoke_passes_with_fake_deployed_endpoints() -> None:
    result = smoke.build_phase4_hardware_demo_smoke(
        urlopen=fake_urlopen_from(passing_routes())
    )

    assert result["artifact_kind"] == "phase4_hardware_demo_smoke_result"
    assert result["status"] == "passed"
    assert result["admin_base_url"] == "http://scout.local:9110"
    assert result["runtime_base_url"] == "http://scout.local:9099"
    assert result["boundaries"]["read_only_http_get_only"] is True
    assert result["boundaries"]["secrets_in_output_allowed"] is False
    assert result["counts"] == {"passed": 6, "failed": 0, "endpoint_count": 6}
    assert [endpoint["endpoint_id"] for endpoint in result["endpoint_statuses"]] == [
        "admin_health",
        "pretrip_admin",
        "pretrip_project",
        "assistant_status",
        "admin_preview_status",
        "runtime_health",
    ]
    assert all(endpoint["method"] == "GET" for endpoint in result["endpoint_statuses"])


def test_output_summarizes_payloads_without_echoing_secrets_or_full_body() -> None:
    routes = passing_routes()
    routes["http://scout.local:9110/assistant/status"] = FakeResponse(
        payload={
            "read_only": True,
            "provider": "mock",
            "provider_class": "MockAssistantProvider",
            "token_values_exposed": False,
            "readiness_starts_local_model": False,
            "status_model_switch_allowed": False,
            "api_token": "should-not-appear",
            "authorization": "should-not-appear",
        }
    )

    result = smoke.build_phase4_hardware_demo_smoke(
        urlopen=fake_urlopen_from(routes)
    )
    serialized = json.dumps(result)

    assert result["status"] == "passed"
    assert "should-not-appear" not in serialized
    assert "api_token" not in serialized
    assert "authorization" not in serialized


def test_admin_auth_header_is_sent_only_to_admin_endpoints_without_echoing_token() -> None:
    calls: list[dict[str, str | None]] = []
    result = smoke.build_phase4_hardware_demo_smoke(
        admin_auth_token="secret-token",
        admin_basic_username="scout-admin",
        urlopen=recording_urlopen_from(passing_routes(), calls),
    )
    serialized = json.dumps(result)

    assert result["status"] == "passed"
    assert result["auth"] == {
        "admin_auth_header_sent": True,
        "admin_auth_scheme": "basic",
        "admin_basic_username": "scout-admin",
        "token_value_exposed": False,
    }
    assert "secret-token" not in serialized
    assert "Authorization" not in serialized
    assert "authorization" not in serialized
    admin_calls = [call for call in calls if call["url"].startswith("http://scout.local:9110")]
    runtime_calls = [call for call in calls if call["url"].startswith("http://scout.local:9099")]
    assert admin_calls
    assert runtime_calls == [
        {
            "url": "http://scout.local:9099/health",
            "authorization": None,
        }
    ]
    assert all((call["authorization"] or "").startswith("Basic ") for call in admin_calls)


def test_failed_assistant_boundary_marks_result_failed() -> None:
    routes = passing_routes()
    routes["http://scout.local:9110/assistant/status"] = FakeResponse(
        payload={
            "read_only": False,
            "provider": "pydantic_ai",
            "token_values_exposed": True,
            "readiness_starts_local_model": True,
            "status_model_switch_allowed": True,
        }
    )

    result = smoke.build_phase4_hardware_demo_smoke(
        urlopen=fake_urlopen_from(routes)
    )
    assistant = next(
        endpoint
        for endpoint in result["endpoint_statuses"]
        if endpoint["endpoint_id"] == "assistant_status"
    )

    assert result["status"] == "failed"
    assert assistant["status"] == "failed"
    assert "assistant_status:read_only!=True" in assistant["missing"]
    assert "assistant_status:token_values_exposed!=False" in assistant["missing"]


def test_runtime_health_degraded_marks_result_failed() -> None:
    routes = passing_routes()
    routes["http://scout.local:9099/health"] = FakeResponse(
        payload={"status": "degraded", "runtime_profile": "pi-field"}
    )

    result = smoke.build_phase4_hardware_demo_smoke(
        urlopen=fake_urlopen_from(routes)
    )
    runtime = result["endpoint_statuses"][-1]

    assert result["status"] == "failed"
    assert runtime["endpoint_id"] == "runtime_health"
    assert runtime["missing"] == ["runtime_health:status_not_ok"]


def test_request_failure_is_reported_without_real_network() -> None:
    def failing_urlopen(_request, timeout):
        assert timeout == 3.0
        raise urllib.error.URLError("connection refused")

    result = smoke.build_phase4_hardware_demo_smoke(urlopen=failing_urlopen)

    assert result["status"] == "failed"
    assert result["counts"]["failed"] == 6
    assert result["endpoint_statuses"][0]["summary"] == "request failed: URLError"
    assert result["endpoint_statuses"][0]["missing"] == [
        "admin_health:request_failed:URLError"
    ]


def test_custom_base_urls_are_normalized() -> None:
    admin_base = "http://demo.local:9110"
    runtime_base = "http://demo.local:9099"
    result = smoke.build_phase4_hardware_demo_smoke(
        admin_base_url=f"{admin_base}/",
        runtime_base_url=f"{runtime_base}/",
        urlopen=fake_urlopen_from(
            passing_routes(admin_base=admin_base, runtime_base=runtime_base)
        ),
    )

    assert result["status"] == "passed"
    assert result["admin_base_url"] == admin_base
    assert result["runtime_base_url"] == runtime_base


def test_base_url_rejects_credentials() -> None:
    with pytest.raises(ValueError, match="credentials"):
        smoke.build_phase4_hardware_demo_smoke(
            admin_base_url="http://user:token@scout.local:9110",
            urlopen=fake_urlopen_from({}),
        )


def test_admin_token_resolver_prefers_file_without_exposing_value(tmp_path: Path) -> None:
    token_file = tmp_path / "admin-token"
    token_file.write_text("file-token\n", encoding="utf-8")

    assert (
        smoke._resolve_admin_auth_token(
            token_env="SCOUT_ADMIN_ACCESS_TOKEN",
            token_file=str(token_file),
            environ={"SCOUT_ADMIN_ACCESS_TOKEN": "env-token"},
        )
        == "file-token"
    )
    assert (
        smoke._resolve_admin_auth_token(
            token_env="SCOUT_ADMIN_ACCESS_TOKEN",
            token_file=str(tmp_path / "missing-token"),
            environ={"SCOUT_ADMIN_ACCESS_TOKEN": "env-token"},
        )
        == "env-token"
    )


def test_cli_help_names_default_lan_targets_without_network() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "phase4_hardware_demo_smoke.py"),
            "--help",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert "--admin-base-url" in completed.stdout
    assert "--runtime-base-url" in completed.stdout
    assert "--admin-basic-username" in completed.stdout
    assert "--admin-token-env" in completed.stdout
    assert "--admin-token-file" in completed.stdout
