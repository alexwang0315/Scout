from __future__ import annotations

import os
from pathlib import Path

from fastapi.testclient import TestClient

from scout.agents import PydanticScoutAgentProvider
from scout.api.routes import create_app
from scout.cli.pydantic_smoke import run_smoke
from scout.main import create_default_app


def make_client(tmp_path: Path) -> TestClient:
    app = create_app(
        tmp_path / "api.sqlite",
        root=Path(__file__).resolve().parents[1],
        eval_jsonl_path=tmp_path / "evals" / "workflow_compiler.jsonl",
    )
    return TestClient(app)


def test_request_installs_low_risk_workflow_and_learning_artifact(
    tmp_path: Path,
) -> None:
    client = make_client(tmp_path)

    response = client.post(
        "/requests",
        json={
            "user_id": "user-1",
            "user_text": "Remind me in 10 minutes.",
            "active_context": {"now": "2026-06-08T00:00:00+00:00"},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "installed"
    workflow_id = payload["workflow_id"]

    workflows = client.get("/workflows", params={"user_id": "user-1"}).json()
    assert workflows["workflows"][0]["id"] == workflow_id

    artifact_payload = client.get(
        "/learning-artifacts",
        params={"user_id": "user-1"},
    ).json()
    assert artifact_payload["learning_artifacts"]


def test_default_app_is_cwd_independent_and_persists_restart_state(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "state" / "scout-ai-os.sqlite"
    monkeypatch.setenv("SCOUT_AI_OS_DATABASE_PATH", str(database_path))
    monkeypatch.chdir(tmp_path)

    first = TestClient(create_default_app())
    created = first.post(
        "/requests",
        json={
            "user_id": "user-1",
            "user_text": "Remind me in 10 minutes.",
            "active_context": {"now": "2026-06-08T00:00:00+00:00"},
        },
    ).json()
    assert created["status"] == "installed"
    assert first.get("/capabilities").json()["capabilities"]

    restarted = TestClient(create_default_app())
    workflows = restarted.get(
        "/workflows",
        params={"user_id": "user-1"},
    ).json()["workflows"]

    assert database_path.exists()
    assert [workflow["id"] for workflow in workflows] == [created["workflow_id"]]
    assert restarted.get("/capabilities").json()["capabilities"]


def test_request_can_use_pydantic_ai_provider(tmp_path: Path) -> None:
    app = create_app(
        tmp_path / "api.sqlite",
        root=Path(__file__).resolve().parents[1],
        provider=PydanticScoutAgentProvider(),
        eval_jsonl_path=tmp_path / "evals" / "workflow_compiler.jsonl",
    )
    client = TestClient(app)

    response = client.post(
        "/requests",
        json={
            "user_id": "user-1",
            "user_text": "Remind me in 10 minutes.",
            "active_context": {"now": "2026-06-08T00:00:00+00:00"},
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "installed"


def test_request_needing_approval_saves_pending_workflow(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    response = client.post(
        "/requests",
        json={
            "user_id": "user-1",
            "user_text": "Notify me 100 meters before the next campsite.",
            "active_context": {},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "needs_approval"

    workflow_id = payload["workflow_id"]
    approve = client.post(
        f"/workflows/{workflow_id}/approve",
        json={"user_id": "user-1", "approval_note": "Trip only."},
    )
    assert approve.status_code == 200
    loaded = client.get(
        f"/workflows/{workflow_id}",
        params={"user_id": "user-1"},
    ).json()
    assert loaded["workflow"]["status"] == "active"


def test_approved_permanent_time_workflow_executes_with_approval_receipt(
    tmp_path: Path,
) -> None:
    client = make_client(tmp_path)
    created = client.post(
        "/requests",
        json={
            "user_id": "user-1",
            "user_text": "Always remind me in 10 minutes.",
            "active_context": {"now": "2026-06-08T00:00:00+00:00"},
        },
    ).json()
    assert created["status"] == "needs_approval"

    approved = client.post(
        f"/workflows/{created['workflow_id']}/approve",
        json={"user_id": "user-1", "approval_note": "Approved recurring reminder."},
    )
    tick = client.post("/runtime/tick")

    assert approved.status_code == 200
    assert tick.json()["ran"] == 1
    assert tick.json()["paused"] == 0
    loaded = client.get(
        f"/workflows/{created['workflow_id']}",
        params={"user_id": "user-1"},
    ).json()
    assert loaded["workflow"]["status"] == "active"
    assert {event["event_type"] for event in loaded["events"]} >= {
        "workflow.approved",
        "notification.sent",
    }


def test_workflow_lookup_and_approval_fail_closed_across_users(
    tmp_path: Path,
) -> None:
    client = make_client(tmp_path)
    created = client.post(
        "/requests",
        json={
            "user_id": "user-1",
            "user_text": "Notify me 100 meters before the next campsite.",
            "active_context": {},
        },
    ).json()

    lookup = client.get(
        f"/workflows/{created['workflow_id']}",
        params={"user_id": "user-2"},
    )
    approval = client.post(
        f"/workflows/{created['workflow_id']}/approve",
        json={"user_id": "user-2", "approval_note": "Not the owner."},
    )

    assert lookup.status_code == 403
    assert approval.status_code == 403


def test_cancelled_workflow_cannot_be_reactivated_by_approval(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    created = client.post(
        "/requests",
        json={
            "user_id": "user-1",
            "user_text": "Notify me 100 meters before the next campsite.",
            "active_context": {},
        },
    ).json()
    client.post(
        f"/workflows/{created['workflow_id']}/cancel",
        json={"user_id": "user-1", "reason": "Cancelled before approval."},
    )

    approval = client.post(
        f"/workflows/{created['workflow_id']}/approve",
        json={"user_id": "user-1", "approval_note": "Too late."},
    )

    assert approval.status_code == 409


def test_request_builds_and_sandboxes_missing_low_risk_capability(
    tmp_path: Path,
) -> None:
    client = make_client(tmp_path)

    response = client.post(
        "/requests",
        json={
            "user_id": "user-1",
            "user_text": "Generate a parser for this CSV format.",
            "active_context": {},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "capability_needs_approval"
    assert payload["workflow_id"] is None
    assert payload["capability"]["name"] == "csv_parser"
    assert payload["capability"]["status"] == "candidate"
    assert payload["sandbox"]["passed"] is True
    assert client.get(
        "/workflows",
        params={"user_id": "user-1"},
    ).json()["workflows"] == []

    repeated = client.post(
        "/requests",
        json={
            "user_id": "user-1",
            "user_text": "Generate a parser for this CSV format.",
            "active_context": {},
        },
    )
    assert repeated.status_code == 409
    assert client.get(
        "/workflows",
        params={"user_id": "user-1"},
    ).json()["workflows"] == []

    approved = client.post(
        "/capabilities/csv_parser/approve",
        json={"user_id": "user-1", "approval_note": "Metadata reviewed."},
    )
    assert approved.status_code == 200
    assert approved.json()["capability"]["runtime_available"] is False

    after_approval = client.post(
        "/requests",
        json={
            "user_id": "user-1",
            "user_text": "Generate a parser for this CSV format.",
            "active_context": {},
        },
    )
    assert after_approval.status_code == 409
    assert client.get(
        "/workflows",
        params={"user_id": "user-1"},
    ).json()["workflows"] == []


def test_ambiguous_time_request_fails_closed_without_workflow(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    response = client.post(
        "/requests",
        json={
            "user_id": "user-1",
            "user_text": "Remind me later.",
            "active_context": {},
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "refused"
    assert "run_at" in response.json()["message"]
    assert client.get(
        "/workflows",
        params={"user_id": "user-1"},
    ).json()["workflows"] == []


def test_cancel_workflow_and_list_capabilities(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    created = client.post(
        "/requests",
        json={
            "user_id": "user-1",
            "user_text": "Remind me in 10 minutes.",
            "active_context": {"now": "2026-06-08T00:00:00+00:00"},
        },
    ).json()

    cancelled = client.post(
        f"/workflows/{created['workflow_id']}/cancel",
        json={"user_id": "user-1", "reason": "No longer needed."},
    )

    assert cancelled.status_code == 200
    capabilities = client.get("/capabilities").json()["capabilities"]
    assert {capability["name"] for capability in capabilities} >= {
        "manual_notification",
        "time_reminder",
        "json_transform",
        "scout.ui.action_plan",
    }
    assert all("status" in capability for capability in capabilities)


def test_generated_capability_candidate_requires_approval_then_installs_metadata(
    tmp_path: Path,
) -> None:
    client = make_client(tmp_path)

    created = client.post(
        "/capabilities/build-candidate",
        json={
            "user_id": "user-1",
            "capability_name": "payload_echo",
            "purpose": "Echo a low-risk JSON payload for tests.",
            "input_schema": {"type": "object"},
            "output_schema": {"type": "object"},
            "risk_level": "low",
        },
    )

    assert created.status_code == 200
    payload = created.json()
    assert payload["status"] == "needs_approval"
    assert payload["capability"]["name"] == "payload_echo"
    assert payload["capability"]["status"] == "candidate"
    assert payload["capability"]["source"] == "generated_candidate"
    assert payload["permission"]["requires_user_approval"] is True
    assert payload["sandbox"]["passed"] is True

    approved = client.post(
        "/capabilities/payload_echo/approve",
        json={"user_id": "user-1", "approval_note": "Sandbox passed."},
    )

    assert approved.status_code == 200
    approved_payload = approved.json()
    assert approved_payload["status"] == "approved"
    assert approved_payload["capability"]["status"] == "installed"
    assert approved_payload["capability"]["source"] == "generated_approved"
    assert approved_payload["capability"]["runtime_available"] is False

    capabilities = client.get("/capabilities").json()["capabilities"]
    payload_echo = next(
        capability for capability in capabilities if capability["name"] == "payload_echo"
    )
    assert payload_echo["status"] == "installed"
    assert payload_echo["runtime_available"] is False


def test_generated_capability_owner_and_builtin_name_are_protected(
    tmp_path: Path,
) -> None:
    client = make_client(tmp_path)
    candidate = client.post(
        "/capabilities/build-candidate",
        json={
            "user_id": "user-1",
            "capability_name": "owned_parser",
            "purpose": "Parse a bounded local payload.",
            "input_schema": {"type": "object"},
            "output_schema": {"type": "object"},
            "risk_level": "low",
        },
    )
    assert candidate.status_code == 200

    wrong_owner = client.post(
        "/capabilities/owned_parser/approve",
        json={"user_id": "user-2", "approval_note": "Not the owner."},
    )
    collision = client.post(
        "/capabilities/build-candidate",
        json={
            "user_id": "user-1",
            "capability_name": "manual_notification",
            "purpose": "Attempt to replace a built-in.",
            "input_schema": {"type": "object"},
            "output_schema": {"type": "object"},
            "risk_level": "low",
        },
    )

    assert wrong_owner.status_code == 403
    assert collision.status_code == 409
    builtins = client.get("/capabilities").json()["capabilities"]
    manual = next(item for item in builtins if item["name"] == "manual_notification")
    assert manual["source"] == "builtin"


def test_generated_capability_candidate_denies_non_low_risk_request(
    tmp_path: Path,
) -> None:
    client = make_client(tmp_path)

    response = client.post(
        "/capabilities/build-candidate",
        json={
            "user_id": "user-1",
            "capability_name": "dangerous_tool",
            "purpose": "Attempt a high-risk action.",
            "input_schema": {"type": "object"},
            "output_schema": {"type": "object"},
            "risk_level": "high",
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "refused"


def test_learning_artifact_approval_endpoint_appends_eval_case(
    tmp_path: Path,
) -> None:
    client = make_client(tmp_path)
    client.post(
        "/requests",
        json={
            "user_id": "user-1",
            "user_text": "Remind me in 10 minutes.",
            "active_context": {"now": "2026-06-08T00:00:00+00:00"},
        },
    )
    artifact = client.get(
        "/learning-artifacts",
        params={"user_id": "user-1"},
    ).json()["learning_artifacts"][0]

    approved = client.post(
        f"/learning-artifacts/{artifact['id']}/approve",
        json={"user_id": "user-1", "approval_note": "Looks reusable."},
    )

    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    assert (tmp_path / "evals" / "workflow_compiler.jsonl").exists()


def test_learning_artifacts_are_bound_to_their_user(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    client.post(
        "/requests",
        json={
            "user_id": "user-1",
            "user_text": "Remind me in 10 minutes.",
            "active_context": {"now": "2026-06-08T00:00:00+00:00"},
        },
    )
    artifact = client.get(
        "/learning-artifacts",
        params={"user_id": "user-1"},
    ).json()["learning_artifacts"][0]

    hidden = client.get(
        "/learning-artifacts",
        params={"user_id": "user-2"},
    )
    approval = client.post(
        f"/learning-artifacts/{artifact['id']}/approve",
        json={"user_id": "user-2", "approval_note": "Not the owner."},
    )

    assert hidden.status_code == 200
    assert hidden.json()["learning_artifacts"] == []
    assert approval.status_code == 403


def test_runtime_tick_endpoint_returns_summary(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    response = client.post("/runtime/tick")

    assert response.status_code == 200
    assert response.json()["checked"] == 0


def test_runtime_tick_executes_due_notification_through_api(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    created = client.post(
        "/requests",
        json={
            "user_id": "user-1",
            "user_text": "Remind me in 10 minutes.",
            "active_context": {"now": "2026-06-08T00:00:00+00:00"},
        },
    ).json()

    tick = client.post("/runtime/tick")

    assert tick.status_code == 200
    assert tick.json()["checked"] == 1
    assert tick.json()["ran"] == 1
    loaded = client.get(
        f"/workflows/{created['workflow_id']}",
        params={"user_id": "user-1"},
    ).json()
    assert loaded["workflow"]["status"] == "completed"
    assert any(
        event["event_type"] == "notification.sent"
        for event in loaded["events"]
    )


def test_background_scheduler_status_disabled_by_default(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    response = client.get("/runtime/scheduler")

    assert response.status_code == 200
    assert response.json() == {
        "enabled": False,
        "running": False,
        "interval_seconds": None,
        "tick_count": 0,
        "last_error": None,
        "last_result": None,
    }


def test_background_scheduler_lifespan_can_be_enabled(tmp_path: Path) -> None:
    app = create_app(
        tmp_path / "api.sqlite",
        root=Path(__file__).resolve().parents[1],
        enable_background_scheduler=True,
        background_scheduler_interval_seconds=0.01,
    )

    with TestClient(app) as client:
        response = client.get("/runtime/scheduler")
        assert response.status_code == 200
        payload = response.json()
        assert payload["enabled"] is True
        assert payload["running"] is True
        assert payload["interval_seconds"] == 0.01

    services = app.state.scout_services
    assert services.background_scheduler is not None
    assert services.background_scheduler.running is False


def test_request_router_preview_routes_ui_operation_to_bridge(
    tmp_path: Path,
) -> None:
    client = make_client(tmp_path)

    response = client.post(
        "/request-router/preview",
        json={
            "user_id": "user-1",
            "user_text": "請幫我關掉所有地圖圖層，只留下 risk score 相關圖層。",
            "active_context": {"surface": "pretrip"},
        },
    )

    assert response.status_code == 200
    route = response.json()["route"]
    assert route["route_class"] == "ui_operation"
    assert route["tool_id"] == "scout.ui.action_plan"
    assert route["artifact"]["artifact_version"] == "scout_ui_action_plan.v0"
    assert route["permission"]["allowed"] is True


def test_request_endpoint_returns_ui_plan_without_installing_workflow(
    tmp_path: Path,
) -> None:
    client = make_client(tmp_path)

    response = client.post(
        "/requests",
        json={
            "user_id": "user-1",
            "user_text": "請幫我關掉所有地圖圖層，只留下 risk score 相關圖層。",
            "active_context": {"surface": "pretrip"},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ui_action_planned"
    assert payload["workflow_id"] is None
    assert payload["ui_action_plan"]["status"] == "planned"
    workflows = client.get("/workflows", params={"user_id": "user-1"}).json()
    assert workflows["workflows"] == []


def test_request_endpoint_requires_confirmation_for_workspace_ui_intent(
    tmp_path: Path,
) -> None:
    client = make_client(tmp_path)

    response = client.post(
        "/requests",
        json={
            "user_id": "user-1",
            "user_text": "用目前地圖點新增一個 CP。",
            "active_context": {"surface": "pretrip"},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ui_action_needs_confirmation"
    assert payload["workflow_id"] is None
    assert payload["route"]["permission"]["requires_user_approval"] is True


def test_request_endpoint_refuses_boundary_request_without_workflow(
    tmp_path: Path,
) -> None:
    client = make_client(tmp_path)

    response = client.post(
        "/requests",
        json={
            "user_id": "user-1",
            "user_text": "請直接觸發 Ln 並發送 SOS",
            "active_context": {"surface": "debug"},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "refused"
    assert payload["workflow_id"] is None
    assert payload["route"]["permission"]["allowed"] is False
    workflows = client.get("/workflows", params={"user_id": "user-1"}).json()
    assert workflows["workflows"] == []


def test_pydantic_smoke_loads_repo_env_without_printing_secret(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("SCOUT_AI_OS_MODEL", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("OPENROUTER_API_KEY=sk-test-secret\n")

    result = run_smoke(
        user_text="Remind me in 10 minutes.",
        user_id="user-1",
        now="2026-06-08T00:00:00+00:00",
        repo_root=Path(__file__).resolve().parents[1],
        env_file=env_file,
    )

    assert result["env_file_loaded"] is True
    assert result["openrouter_api_key_present"] is True
    assert result["model_policy"]["mode"] == "local_function"
    assert "sk-test-secret" not in str(result)
    assert os.environ["OPENROUTER_API_KEY"] == "sk-test-secret"


def test_pydantic_smoke_blocks_external_model_when_key_is_missing(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("SCOUT_AI_OS_MODEL", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("SCOUT_AI_OS_MODEL=openrouter:z-ai/glm-5.2\n")

    result = run_smoke(
        user_text="Remind me in 10 minutes.",
        user_id="user-1",
        now="2026-06-08T00:00:00+00:00",
        repo_root=Path(__file__).resolve().parents[1],
        env_file=env_file,
    )

    assert result["request_status"] == "model_config_blocked"
    assert result["workflow_count"] == 0
    assert result["model"] == "openrouter:z-ai/glm-5.2"
    assert result["model_policy"]["source"] == "env"
    assert result["model_policy"]["missing_credential_env"] == [
        "OPENROUTER_API_KEY"
    ]
    assert "OPENROUTER_API_KEY=" not in str(result)


def test_pydantic_smoke_blocks_nvidia_model_when_key_is_missing(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    monkeypatch.delenv("SCOUT_AI_OS_MODEL", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "SCOUT_AI_OS_MODEL=nvidia:nvidia/llama-3.3-nemotron-super-49b-v1.5\n"
    )

    result = run_smoke(
        user_text="Remind me in 10 minutes.",
        user_id="user-1",
        now="2026-06-08T00:00:00+00:00",
        repo_root=Path(__file__).resolve().parents[1],
        env_file=env_file,
    )

    assert result["request_status"] == "model_config_blocked"
    assert result["workflow_count"] == 0
    assert result["model"] == "nvidia/llama-3.3-nemotron-super-49b-v1.5"
    assert result["model_policy"]["provider"] == "nvidia"
    assert (
        result["model_policy"]["pydantic_ai_model"]
        == "nvidia:nvidia/llama-3.3-nemotron-super-49b-v1.5"
    )
    assert result["model_policy"]["missing_credential_env"] == ["NVIDIA_API_KEY"]
    assert result["nvidia_api_key_present"] is False
    assert "NVIDIA_API_KEY=" not in str(result)


def test_pydantic_smoke_reports_ui_router_result_without_workflow(
    tmp_path: Path,
) -> None:
    result = run_smoke(
        user_text="請幫我關掉所有地圖圖層，只留下 risk score 相關圖層。",
        user_id="user-1",
        now="2026-06-08T00:00:00+00:00",
        surface="pretrip",
        repo_root=Path(__file__).resolve().parents[1],
        env_file=tmp_path / "missing.env",
    )

    assert result["request_status"] == "ui_action_planned"
    assert result["workflow_count"] == 0
    assert result["route_class"] == "ui_operation"
    assert result["ui_action_plan_status"] == "planned"
    assert result["ui_action_kind"] == "set_layer_preset"
