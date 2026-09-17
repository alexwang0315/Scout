"""GET-only API and page for Scout intelligence telemetry."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, Response

from scout.nextgen.dashboard_telemetry import (
    IntelligenceTelemetryReader,
    SQLiteBackgroundIntelligenceTelemetryReader,
    unavailable_telemetry_snapshot,
)


DEFAULT_INTELLIGENCE_TELEMETRY_PAGE = (
    Path(__file__).resolve().parents[3]
    / "docs"
    / "admin"
    / "scout-intelligence-telemetry.html"
)


def create_intelligence_telemetry_router(
    *,
    reader: IntelligenceTelemetryReader | None = None,
    page_path: Path = DEFAULT_INTELLIGENCE_TELEMETRY_PAGE,
) -> APIRouter:
    telemetry_reader = (
        reader or SQLiteBackgroundIntelligenceTelemetryReader.from_environ()
    )
    router = APIRouter(prefix="/admin/intelligence", tags=["intelligence-telemetry"])

    @router.get("", response_class=HTMLResponse)
    def intelligence_telemetry_page() -> Response:
        if not page_path.is_file():
            raise HTTPException(
                status_code=404,
                detail="Intelligence telemetry page not found",
            )
        return Response(
            page_path.read_text(encoding="utf-8"),
            media_type="text/html",
            headers={"Cache-Control": "no-store"},
        )

    @router.get("/telemetry")
    def intelligence_telemetry_snapshot() -> JSONResponse:
        try:
            snapshot = telemetry_reader.snapshot()
        except Exception:
            snapshot = unavailable_telemetry_snapshot(
                status="degraded",
                reason="reader_failure",
                configured=True,
            )
        return JSONResponse(
            snapshot.model_dump(mode="json"),
            headers={"Cache-Control": "no-store"},
        )

    return router


__all__ = [
    "DEFAULT_INTELLIGENCE_TELEMETRY_PAGE",
    "create_intelligence_telemetry_router",
]
