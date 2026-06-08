"""FastAPI routes for Scout AI OS MVP."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from scout.agents import (
    CodeBuilderAgent,
    DeterministicScoutAgentProvider,
    ExecutionPlannerAgent,
    LearningAgent,
    ScoutAgentProvider,
    ScoutDeps,
    WorkflowCompilerAgent,
)
from scout.runtime import ActionExecutor, RuntimeExecutor, Scheduler
from scout.services import (
    CapabilityRegistry,
    LearningStore,
    MemoryStore,
    NotificationGateway,
    PermissionGate,
    WorkflowRecord,
    WorkflowStore,
    open_database,
)
from scout.services.docs_search import DocsSearch
from scout.services.sandbox_runner import SandboxRunner


class RequestInput(BaseModel):
    user_id: str
    user_text: str
    active_context: dict[str, Any] = Field(default_factory=dict)


class ApprovalInput(BaseModel):
    user_id: str
    approval_note: str = ""


class CancelInput(BaseModel):
    user_id: str
    reason: str = ""


@dataclass
class ScoutApiServices:
    workflow_store: WorkflowStore
    capability_registry: CapabilityRegistry
    memory_store: MemoryStore
    learning_store: LearningStore
    permission_gate: PermissionGate
    notification_gateway: NotificationGateway
    sandbox: SandboxRunner
    docs_search: DocsSearch
    scheduler: Scheduler
    workflow_compiler: WorkflowCompilerAgent
    execution_planner: ExecutionPlannerAgent
    code_builder: CodeBuilderAgent
    learner: LearningAgent

    def deps(self, user_id: str, active_context: dict[str, Any] | None = None) -> ScoutDeps:
        return ScoutDeps(
            capability_registry=self.capability_registry,
            memory_store=self.memory_store,
            workflow_store=self.workflow_store,
            sandbox=self.sandbox,
            permission_gate=self.permission_gate,
            notification_gateway=self.notification_gateway,
            docs_search=self.docs_search,
            user_id=user_id,
            active_context=dict(active_context or {}),
        )


def create_services(
    database_path: str | Path = ":memory:",
    *,
    root: Path | None = None,
    provider: ScoutAgentProvider | None = None,
    eval_jsonl_path: Path | None = None,
) -> ScoutApiServices:
    project_root = root or Path.cwd()
    connection = open_database(database_path)
    workflow_store = WorkflowStore(connection)
    capability_registry = CapabilityRegistry(connection)
    builtins_path = project_root / "src/scout/capabilities/builtins"
    if builtins_path.exists():
        capability_registry.load_builtins(builtins_path)
    memory_store = MemoryStore(connection)
    learning_store = LearningStore(
        connection,
        memory_store,
        eval_jsonl_path=eval_jsonl_path,
    )
    permission_gate = PermissionGate()
    notification_gateway = NotificationGateway(workflow_store)
    sandbox = SandboxRunner()
    docs_search = DocsSearch(project_root / "docs")
    action_executor = ActionExecutor(notification_gateway, capability_registry)
    runtime_executor = RuntimeExecutor(
        workflow_store,
        permission_gate,
        action_executor,
    )
    scheduler = Scheduler(runtime_executor)
    agent_provider = provider or DeterministicScoutAgentProvider()
    return ScoutApiServices(
        workflow_store=workflow_store,
        capability_registry=capability_registry,
        memory_store=memory_store,
        learning_store=learning_store,
        permission_gate=permission_gate,
        notification_gateway=notification_gateway,
        sandbox=sandbox,
        docs_search=docs_search,
        scheduler=scheduler,
        workflow_compiler=WorkflowCompilerAgent(agent_provider),
        execution_planner=ExecutionPlannerAgent(agent_provider),
        code_builder=CodeBuilderAgent(agent_provider),
        learner=LearningAgent(agent_provider),
    )


def create_router(services: ScoutApiServices) -> APIRouter:
    router = APIRouter()

    @router.post("/requests")
    def create_request(payload: RequestInput) -> dict[str, Any]:
        deps = services.deps(payload.user_id, payload.active_context)
        workflow = services.workflow_compiler.compile(payload.user_text, deps)
        plan = services.execution_planner.plan(workflow, deps)
        decision = services.permission_gate.evaluate_workflow(workflow)

        if not decision.allowed:
            return {
                "status": "refused",
                "workflow_id": None,
                "message": decision.user_message,
                "permission": decision.model_dump(mode="json"),
                "plan": plan.model_dump(mode="json"),
            }

        if decision.requires_user_approval:
            workflow_id = services.workflow_store.save_pending(
                workflow,
                user_id=payload.user_id,
            )
            return {
                "status": "needs_approval",
                "workflow_id": workflow_id,
                "message": decision.user_message,
                "permission": decision.model_dump(mode="json"),
                "plan": plan.model_dump(mode="json"),
            }

        workflow_id = services.workflow_store.install(
            workflow,
            user_id=payload.user_id,
        )
        bundle = services.learner.propose(workflow, deps, execution_plan=plan)
        learning_artifact_ids = services.learning_store.save_bundle(
            bundle,
            source_workflow_id=workflow_id,
        )
        return {
            "status": "installed",
            "workflow_id": workflow_id,
            "message": "Workflow installed.",
            "plan": plan.model_dump(mode="json"),
            "learning_artifact_ids": learning_artifact_ids,
        }

    @router.get("/workflows")
    def list_workflows(
        user_id: str = Query(...),
        status: str | None = Query(None),
    ) -> dict[str, Any]:
        workflows = [
            _workflow_record_to_dict(record)
            for record in services.workflow_store.list_workflows(user_id)
            if status is None or record.status == status
        ]
        return {"workflows": workflows}

    @router.get("/workflows/{workflow_id}")
    def get_workflow(workflow_id: str) -> dict[str, Any]:
        record = services.workflow_store.get_workflow(workflow_id)
        if record is None:
            raise HTTPException(status_code=404, detail="workflow not found")
        return {
            "workflow": _workflow_record_to_dict(record),
            "events": services.workflow_store.list_events(workflow_id),
        }

    @router.post("/workflows/{workflow_id}/approve")
    def approve_workflow(
        workflow_id: str,
        payload: ApprovalInput,
    ) -> dict[str, Any]:
        record = services.workflow_store.get_workflow(workflow_id)
        if record is None:
            raise HTTPException(status_code=404, detail="workflow not found")
        if record.user_id != payload.user_id:
            raise HTTPException(status_code=403, detail="workflow belongs to another user")
        services.workflow_store.activate(workflow_id, payload.approval_note)
        return {"status": "approved", "workflow_id": workflow_id}

    @router.post("/workflows/{workflow_id}/cancel")
    def cancel_workflow(
        workflow_id: str,
        payload: CancelInput,
    ) -> dict[str, Any]:
        record = services.workflow_store.get_workflow(workflow_id)
        if record is None:
            raise HTTPException(status_code=404, detail="workflow not found")
        if record.user_id != payload.user_id:
            raise HTTPException(status_code=403, detail="workflow belongs to another user")
        services.workflow_store.cancel(workflow_id, payload.reason)
        return {"status": "cancelled", "workflow_id": workflow_id}

    @router.get("/capabilities")
    def list_capabilities() -> dict[str, Any]:
        return {
            "capabilities": [
                spec.model_dump(mode="json")
                for spec in services.capability_registry.list_all()
            ]
        }

    @router.get("/learning-artifacts")
    def list_learning_artifacts(
        status: str | None = Query("pending_review"),
    ) -> dict[str, Any]:
        return {
            "learning_artifacts": [
                _learning_record_to_dict(record)
                for record in services.learning_store.list_artifacts(status)
            ]
        }

    @router.post("/learning-artifacts/{artifact_id}/approve")
    def approve_learning_artifact(
        artifact_id: str,
        payload: ApprovalInput,
    ) -> dict[str, Any]:
        try:
            result = services.learning_store.approve(
                artifact_id,
                user_id=payload.user_id,
                approval_note=payload.approval_note,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="learning artifact not found") from exc
        return {"artifact_id": artifact_id, **result}

    @router.post("/runtime/tick")
    def runtime_tick() -> dict[str, Any]:
        return asdict(services.scheduler.tick())

    return router


def create_app(
    database_path: str | Path = ":memory:",
    *,
    root: Path | None = None,
    provider: ScoutAgentProvider | None = None,
    eval_jsonl_path: Path | None = None,
) -> FastAPI:
    app = FastAPI(title="Scout AI OS", version="0.1.0")
    services = create_services(
        database_path,
        root=root,
        provider=provider,
        eval_jsonl_path=eval_jsonl_path,
    )
    app.state.scout_services = services
    app.include_router(create_router(services))
    return app


def _workflow_record_to_dict(record: WorkflowRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "user_id": record.user_id,
        "name": record.name,
        "status": record.status,
        "lifecycle": record.lifecycle,
        "runtime": record.runtime,
        "workflow": record.workflow.model_dump(mode="json"),
        "next_run_at": record.next_run_at.isoformat() if record.next_run_at else None,
        "retry_count": record.retry_count,
        "created_at": record.created_at.isoformat(),
        "updated_at": record.updated_at.isoformat(),
        "last_error": record.last_error,
    }


def _learning_record_to_dict(record: Any) -> dict[str, Any]:
    return {
        "id": record.id,
        "artifact": record.artifact.model_dump(mode="json"),
        "status": record.status,
        "source_workflow_id": record.source_workflow_id,
        "created_at": record.created_at.isoformat(),
    }


__all__ = [
    "ApprovalInput",
    "CancelInput",
    "RequestInput",
    "ScoutApiServices",
    "create_app",
    "create_router",
    "create_services",
]
