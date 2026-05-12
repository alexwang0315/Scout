from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from admin_after_action import ROOT, build_admin_case_view, list_admin_cases


DEFAULT_ADMIN_PAGE = ROOT / "docs" / "admin" / "phase1-after-action.html"


def create_admin_app(*, incident_store_path: Path | None = None) -> FastAPI:
    app = FastAPI(title="Scout Fusion Admin API")
    app.include_router(create_admin_router(incident_store_path=incident_store_path))
    return app


def create_admin_router(*, incident_store_path: Path | None = None) -> APIRouter:
    router = APIRouter(prefix="/admin", tags=["admin"])
    resolved_incident_store_path = incident_store_path or _incident_store_from_env()

    @router.get("", response_class=HTMLResponse)
    def admin_page() -> str:
        if not DEFAULT_ADMIN_PAGE.exists():
            raise HTTPException(status_code=404, detail="Admin page not found")
        return DEFAULT_ADMIN_PAGE.read_text(encoding="utf-8")

    @router.get("/cases")
    def cases() -> dict[str, Any]:
        return {"cases": list_admin_cases()}

    @router.get("/cases/{case_id}")
    def case(case_id: str) -> dict[str, Any]:
        try:
            return build_admin_case_view(case_id, incident_store_path=resolved_incident_store_path)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Admin case not found") from exc

    return router


def _incident_store_from_env() -> Path | None:
    value = os.getenv("SCOUT_SAFETY_INCIDENT_STORE")
    return Path(value).expanduser() if value else None
