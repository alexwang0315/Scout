from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

from admin_api import create_dashboard_app
from assistant_models import (
    AssistantBoundary,
    ScoutAssistantQuery,
    ScoutAssistantResponse,
)


class QualificationAssistantProvider:
    """Network-free provider used only to prove the Assistant mount boundary."""

    startup_connection_status = "connected:qualification-fixture"

    def answer(
        self,
        query: ScoutAssistantQuery,
        *,
        sources: list[Any] | None = None,
    ) -> ScoutAssistantResponse:
        return ScoutAssistantResponse(
            surface=query.surface,
            answer="Qualification fixture response. No external model was called.",
            sources=list(sources or []),
            boundary=AssistantBoundary(surface=query.surface),
            limitations=["synthetic qualification fixture"],
        )


def create_app():
    workspace_value = os.environ.get("SCOUT_QUALIFICATION_WORKSPACE_ROOT", "").strip()
    if not workspace_value:
        raise RuntimeError("SCOUT_QUALIFICATION_WORKSPACE_ROOT is required")
    workspace_root = Path(workspace_value).expanduser().resolve()
    mode = os.environ.get(
        "SCOUT_QUALIFICATION_ASSISTANT_MODE",
        "disabled",
    ).strip()
    if mode not in {"enabled", "disabled"}:
        raise RuntimeError("qualification Assistant mode must be enabled or disabled")
    enabled = mode == "enabled"
    app = create_dashboard_app(
        pretrip_workspace_root=workspace_root,
        living_sandbox_store_root=workspace_root / ".qualification-living-store",
        contextual_permission_store_root=(
            workspace_root / ".qualification-permission-store"
        ),
        assistant_enabled=enabled,
        assistant_provider=(QualificationAssistantProvider() if enabled else None),
        assistant_environ={
            "SCOUT_AI_ASSISTANT_ENABLED": "1" if enabled else "0",
            "SCOUT_AI_ASSISTANT_PROVIDER": "qualification_fixture",
            "SCOUT_RUNTIME_PROFILE": "dashboard-qualification",
        },
    )
    zero_project_id = "qualification_zero_evidence"
    zero_base_path = f"/admin/pretrip/projects/{zero_project_id}"

    @app.middleware("http")
    async def qualification_zero_evidence_projection(
        request: Request,
        call_next,
    ):
        path = request.url.path
        if request.method != "GET" or not path.startswith(zero_base_path):
            return await call_next(request)
        boundary = {
            "projection_only": True,
            "candidate_only": True,
            "runtime_safety_truth": False,
            "workspace_writes_allowed": False,
        }
        if path == zero_base_path:
            return JSONResponse(
                {
                    "project_id": zero_project_id,
                    "artifact_kind": "qualification_zero_evidence_projection",
                    "schema_version": "qualificationZeroEvidenceProjection.v1",
                    "qualification_fixture_state": "zero_evidence",
                    "status": "ready_empty",
                    "tabs": {},
                    "evidence_timeline": {
                        "categories": [],
                        "counts": {
                            "category_count": 0,
                            "available_category_count": 0,
                            "total_evidence_count": 0,
                        },
                        "boundary": boundary,
                    },
                    "boundary": boundary,
                }
            )
        if path == f"{zero_base_path}/admin-projection":
            return JSONResponse(
                {
                    "project_id": zero_project_id,
                    "artifact_kind": "qualification_zero_admin_projection",
                    "status": "ready_empty",
                    "mission": {"checkpoints": [], "segments": []},
                    "boundary": boundary,
                }
            )
        if path == f"{zero_base_path}/debug-projection-events":
            return JSONResponse(
                {
                    "project_id": zero_project_id,
                    "artifact_kind": "qualification_zero_debug_projection_events",
                    "events": [],
                    "boundary": boundary,
                }
            )
        return await call_next(request)

    return app
