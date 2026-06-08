from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.responses import HTMLResponse, Response

from hardware_readiness_admin_view import (
    DEFAULT_HARDWARE_READINESS_FIXTURE,
    build_hardware_readiness_admin_view,
)


ROOT = Path(__file__).resolve().parent
DEFAULT_HARDWARE_READINESS_PAGE = ROOT / "docs" / "admin" / "phase-3-6-hardware-readiness.html"
DEFAULT_ASSISTANT_UI_SCRIPT = ROOT / "docs" / "admin" / "scout-assistant-ui.js"


def create_hardware_readiness_app(
    *,
    fixture_path: Path | str = DEFAULT_HARDWARE_READINESS_FIXTURE,
) -> FastAPI:
    app = FastAPI(title="Scout Hardware Readiness Admin API")
    app.include_router(create_hardware_readiness_router(fixture_path=fixture_path))
    return app


def create_hardware_readiness_router(
    *,
    fixture_path: Path | str = DEFAULT_HARDWARE_READINESS_FIXTURE,
    page_path: Path | str = DEFAULT_HARDWARE_READINESS_PAGE,
    assistant_ui_script_path: Path | str = DEFAULT_ASSISTANT_UI_SCRIPT,
) -> APIRouter:
    router = APIRouter(prefix="/admin", tags=["hardware-readiness"])
    resolved_fixture_path = Path(fixture_path)
    resolved_page_path = Path(page_path)
    resolved_assistant_ui_script_path = Path(assistant_ui_script_path)

    @router.get("/hardware-readiness", response_class=HTMLResponse)
    def hardware_readiness_page() -> str:
        if not resolved_page_path.exists():
            raise HTTPException(status_code=404, detail="Hardware readiness page not found")
        return resolved_page_path.read_text(encoding="utf-8")

    @router.get("/hardware-readiness/context")
    def hardware_readiness_context(selected_provider_ref: str | None = None) -> dict[str, Any]:
        try:
            return build_hardware_readiness_admin_view(
                fixture_path=resolved_fixture_path,
                selected_provider_ref=selected_provider_ref,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Hardware readiness fixture not found") from exc

    @router.get("/scout-assistant-ui.js")
    def assistant_ui_script() -> Response:
        if not resolved_assistant_ui_script_path.exists():
            raise HTTPException(status_code=404, detail="Assistant UI script not found")
        return Response(
            resolved_assistant_ui_script_path.read_text(encoding="utf-8"),
            media_type="application/javascript",
        )

    return router
