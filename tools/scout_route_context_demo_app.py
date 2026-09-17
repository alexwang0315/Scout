"""Local, read-only Route Context demo. Does not start Dashboard or GIS workers."""

from __future__ import annotations

import argparse
import base64
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.responses import FileResponse, Response  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from starlette.middleware.gzip import GZipMiddleware  # noqa: E402
from starlette.middleware.trustedhost import TrustedHostMiddleware  # noqa: E402

from scout_route_context_demo import RouteContextWorkspace  # noqa: E402

EMPTY_TILE = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGNgYGBgAAAABQABpfZFQAAAAABJRU5ErkJggg==")


def create_app(project_root: Path) -> FastAPI:
    workspace = RouteContextWorkspace(project_root)
    catalog = workspace.catalog()
    app = FastAPI(title="Scout Route Context Demo", docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "[::1]", "testserver"])

    @app.middleware("http")
    async def local_read_only(request: Request, call_next):
        if request.method not in {"GET", "HEAD"}:
            return Response(status_code=405)
        origin = request.headers.get("origin")
        if (origin and origin != f"{request.url.scheme}://{request.url.netloc}") or request.headers.get("sec-fetch-site") == "cross-site":
            return Response(status_code=403)
        response = await call_next(request)
        response.headers.update({
            "Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff", "Cross-Origin-Resource-Policy": "same-origin",
            "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; worker-src 'self' blob:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'",
        })
        return response

    @app.get("/api/context")
    def context():
        return catalog

    @app.get("/tiles/{layer}/{z}/{x}/{y}.png")
    def tile(layer: str, z: int, x: int, y: int):
        try:
            path = workspace.tile(layer, z, x, y)
        except FileNotFoundError:
            return Response(EMPTY_TILE, media_type="image/png", headers={"X-Scout-Tile-Coverage": "missing"})
        except (ValueError, OSError):
            return Response(status_code=404)
        return FileResponse(path, media_type="image/png", headers={"X-Scout-Tile-Coverage": "cached"})

    @app.get("/")
    def page():
        return FileResponse(ROOT / "docs/admin/experiments/route-context/index.html")

    @app.get("/favicon.ico")
    def favicon():
        return Response(status_code=204)

    app.mount("/assets", StaticFiles(directory=ROOT / "docs/admin/experiments/route-context"))
    app.mount("/maplibre", StaticFiles(directory=ROOT / "docs/admin/vendor/maplibre-gl/6.2.0"))
    return app


def main():
    import uvicorn

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--port", type=int, default=19130)
    args = parser.parse_args()
    if args.port in {8000, 8080, 9099, 19110, 19111}:
        parser.error("Select a separate experiment port")
    uvicorn.run(create_app(args.project_root), host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
