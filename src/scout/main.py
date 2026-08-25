"""FastAPI application entry point for Scout AI OS MVP."""

from __future__ import annotations

import os
from pathlib import Path

from scout.api.routes import create_app


DATABASE_PATH_ENV = "SCOUT_AI_OS_DATABASE_PATH"


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def default_database_path() -> str | Path:
    configured = (os.getenv(DATABASE_PATH_ENV) or "").strip()
    if configured:
        return configured if configured == ":memory:" else Path(configured).expanduser()
    state_root = (os.getenv("XDG_STATE_HOME") or "").strip()
    base = Path(state_root).expanduser() if state_root else Path.home() / ".local/state"
    return base / "scout-ai-os" / "scout-ai-os.sqlite"


def create_default_app():
    return create_app(
        database_path=default_database_path(),
        root=project_root(),
    )


app = create_default_app()


__all__ = [
    "DATABASE_PATH_ENV",
    "app",
    "create_default_app",
    "default_database_path",
    "project_root",
]
