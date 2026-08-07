from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from admin_api import create_admin_app, create_dashboard_app
from assistant_provider import MockAssistantProvider
from dashboard_connected_preparation import DashboardConnectedPreparationManager
from runtime_audit_ledger import FileRuntimeAuditLedger


def _write_workspace(root: Path, project_id: str = "trip_001") -> Path:
    project_root = root / project_id
    project_root.mkdir(parents=True)
    (project_root / "project.json").write_text(
        json.dumps({"project_id": project_id}),
        encoding="utf-8",
    )
    return project_root


def test_runtime_audit_storage_cannot_be_nested_in_workspace(
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()

    with pytest.raises(
        ValueError,
        match="runtime audit storage must remain outside",
    ):
        create_admin_app(
            pretrip_workspace_root=workspace_root,
            runtime_audit_root=workspace_root / ".audit",
        )


def test_admin_runtime_audit_api_records_lifecycle_http_and_workspace_io(
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "workspace"
    _write_workspace(workspace_root)
    audit_root = tmp_path / "audit"
    app = create_admin_app(
        pretrip_workspace_root=workspace_root,
        runtime_audit_root=audit_root,
    )

    with TestClient(app) as client:
        dashboard = client.get("/admin/dashboard?api_key=must-not-be-recorded")
        assert dashboard.status_code == 200
        created = client.post(
            "/admin/dashboard/workspaces/trip_001/operation-requests",
            json={
                "operation": "package",
                "confirm_record": True,
                "requested_by": "dashboard_operator",
            },
        )
        assert created.status_code == 201

        response = client.get("/admin/runtime-audit?limit=100")
        assert response.status_code == 200
        payload = response.json()
        assert payload["schema_version"] == "scout_runtime_audit_list.v1"
        assert payload["boundary"] == {
            "telemetry_only": True,
            "runtime_safety_truth": False,
            "raw_payloads_embedded": False,
        }
        assert payload["summary"]["total_events"] >= 4
        assert payload["summary"]["workspace_writes"] == 1
        assert any(
            event["event_type"] == "runtime.instance.started"
            for event in payload["events"]
        )
        assert any(
            event["event_type"] == "http.request.completed"
            and event["route_template"] == "/admin/dashboard"
            for event in payload["events"]
        )
        workspace_events = [
            event
            for event in payload["events"]
            if event["event_type"] == "workspace.io.completed"
        ]
        assert workspace_events[0]["artifact_kind"] == "workspace_operation_request"
        assert workspace_events[0]["record_count"] == 1
        assert workspace_events[0]["artifact_ref_hash"]
        assert "must-not-be-recorded" not in json.dumps(payload)
        assert str(workspace_root) not in json.dumps(payload)

    manifest = json.loads(
        next(audit_root.glob("*/manifest.json")).read_text(encoding="utf-8")
    )
    assert manifest["status"] == "ended"
    assert not any("runtime_audit" in path.name for path in workspace_root.rglob("*"))


def test_runtime_audit_api_accepts_a_complete_local_day_query(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}
    ledger = FileRuntimeAuditLedger(
        root=tmp_path / "audit",
        runtime_instance_id="runtime-api-date-index",
    )
    original_query = ledger.query

    def capture_query(**kwargs: object):
        observed.update(kwargs)
        return original_query(**kwargs)

    monkeypatch.setattr(ledger, "query", capture_query)
    app = create_admin_app(runtime_audit_ledger=ledger)

    with TestClient(app) as client:
        response = client.get(
            "/admin/runtime-audit",
            params={
                "date": "2026-08-07",
                "utc_offset_minutes": 480,
                "include_all": "true",
            },
        )
        invalid = client.get(
            "/admin/runtime-audit",
            params={"include_all": "true"},
        )

    assert response.status_code == 200
    assert observed["day"] == "2026-08-07"
    assert observed["utc_offset_minutes"] == 480
    assert observed["limit"] is None
    assert response.json()["date_index"]["selected_day"] == "2026-08-07"
    assert invalid.status_code == 422


def test_dashboard_assistant_run_is_recorded_without_question_or_answer(
    tmp_path: Path,
) -> None:
    secret_question = "Private question that must never enter the audit ledger"
    app = create_dashboard_app(
        pretrip_workspace_root=tmp_path / "workspace",
        assistant_enabled=True,
        assistant_provider=MockAssistantProvider(),
        assistant_environ={},
        runtime_audit_root=tmp_path / "audit",
    )

    with TestClient(app) as client:
        response = client.post(
            "/assistant/query",
            json={
                "surface": "debug",
                "question": secret_question,
                "project_id": "trip_001",
            },
        )
        assert response.status_code == 200
        answer = response.json()["answer"]

        payload = client.get(
            "/admin/runtime-audit?event_type=agent.run.completed&limit=20"
        ).json()
        assert len(payload["events"]) == 1
        event = payload["events"][0]
        assert event["category"] == "agent"
        assert event["workspace_id"] == "trip_001"
        assert event["duration_ms"] >= 0
        assert event["provider"] == "MockAssistantProvider"
        serialized = json.dumps(payload, ensure_ascii=False)
        assert secret_question not in serialized
        assert answer not in serialized


def test_connected_preparation_records_job_provider_and_workspace_publication(
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "workspace"
    _write_workspace(workspace_root)
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    ledger = FileRuntimeAuditLedger(
        root=tmp_path / "audit",
        runtime_instance_id="runtime-connected-preparation",
    )
    ledger.start(application="scout-dashboard", runtime_profile="test")

    def fake_runner(request: Any) -> dict[str, Any]:
        project_root = Path(request.project_root)
        project_path = project_root / "project.json"
        project = json.loads(project_path.read_text(encoding="utf-8"))
        evidence_ref = "outputs/environment/cwa/weather.json"
        evidence_path = project_root / evidence_ref
        evidence_path.parent.mkdir(parents=True)
        evidence_path.write_text('{"status":"ready"}', encoding="utf-8")
        project.update(
            {
                "cwa_external_api_calls_made": True,
                "cwa_weather_status": "ready",
                "cwa_weather_evidence_ref": evidence_ref,
                "cwa_rainfall_grid_manifest_ref": "outputs/environment/cwa/grid.json",
            }
        )
        project_path.write_text(json.dumps(project), encoding="utf-8")
        return {
            "network_policy": {"network_calls_made": True},
            "boundary": {"external_api_calls_made": True},
        }

    manager = DashboardConnectedPreparationManager(
        workspace_root=workspace_root,
        repo_root=repo_root,
        environ={"CWA_API_KEY": "present-but-never-recorded"},
        runner=fake_runner,
        runtime_audit=ledger,
    )

    result = manager.run_once("trip_001", reason="runtime-audit-test")
    payload = ledger.query(limit=100).model_dump(mode="json")

    assert result["publicationStatus"] == "published"
    assert payload["summary"]["background_jobs"] == 1
    assert payload["summary"]["provider_calls"] == 1
    assert payload["summary"]["workspace_writes"] == 1
    assert any(
        event["event_type"] == "provider.call.completed"
        and event["provider"] == "cwa"
        for event in payload["events"]
    )
    assert "present-but-never-recorded" not in json.dumps(payload)


def test_audit_start_failure_does_not_fail_dashboard_and_is_visible(
    tmp_path: Path,
    monkeypatch,
) -> None:
    ledger = FileRuntimeAuditLedger(
        root=tmp_path / "audit",
        runtime_instance_id="runtime-start-failure",
    )

    def fail_event_write(path: Path, payload: dict[str, object]) -> None:
        raise OSError("simulated audit storage failure")

    monkeypatch.setattr(ledger, "_append_json_line", fail_event_write)
    app = create_admin_app(runtime_audit_ledger=ledger)

    with TestClient(app) as client:
        dashboard = client.get("/admin/dashboard")
        assert dashboard.status_code == 200

        audit = client.get("/admin/runtime-audit").json()
        assert audit["status"] == "degraded"
        assert audit["writer_health"]["status"] == "degraded"
        assert audit["writer_health"]["dropped_event_count"] >= 1
        assert audit["writer_health"]["last_error_code"] in {
            "OSError",
            "RuntimeError",
        }
