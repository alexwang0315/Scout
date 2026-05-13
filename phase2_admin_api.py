from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException

from phase2_admin_preview import build_phase2_admin_preview
from phase2_brain_store import BrainFileStore
from phase2_case_replay_integration import MissingBrainReferenceError


def create_phase2_admin_app(*, brain_store_root: Path | str) -> FastAPI:
    app = FastAPI(title="Scout Fusion Phase 2 Admin Preview API")
    app.include_router(create_phase2_admin_router(brain_store_root=brain_store_root))
    return app


def create_phase2_admin_router(*, brain_store_root: Path | str) -> APIRouter:
    router = APIRouter(prefix="/phase2/admin", tags=["phase2-admin"])
    resolved_brain_store_root = Path(brain_store_root)

    @router.get("/preview")
    def preview(mission_id: str | None = None) -> dict[str, Any]:
        store = BrainFileStore(resolved_brain_store_root)
        try:
            phase2_preview = build_phase2_admin_preview(store, mission_id=mission_id)
        except MissingBrainReferenceError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        payload = asdict(phase2_preview)
        payload["option_set_ids"] = list(phase2_preview.option_set_ids)
        return payload

    return router
