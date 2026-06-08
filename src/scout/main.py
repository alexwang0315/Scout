"""FastAPI application entry point for Scout AI OS MVP."""

from scout.api.routes import create_app


app = create_app()


__all__ = ["app"]
