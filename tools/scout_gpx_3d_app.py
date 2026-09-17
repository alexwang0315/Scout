"""An opt-in local viewer; never boots the Scout production runtime."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, HTTPException, Request  # noqa: E402
from fastapi.responses import FileResponse, Response  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from starlette.middleware.trustedhost import TrustedHostMiddleware  # noqa: E402
from starlette.middleware.gzip import GZipMiddleware  # noqa: E402

from scout_gpx_3d import Gpx3DWorkspace  # noqa: E402
from scout_gpx_3d_terrain import build_display_mesh, sample_prepared_elevation  # noqa: E402


def create_app(project_root: Path) -> FastAPI:
    app = FastAPI(title="Scout GPX × God's Eye View experiment", docs_url=None, redoc_url=None, openapi_url=None)
    workspace = Gpx3DWorkspace(project_root)
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "[::1]", "testserver"])

    @app.middleware("http")
    async def local_read_only(request: Request, call_next):
        if request.method not in {"GET", "HEAD"}:
            return Response(status_code=405)
        # Prevent a different browser origin from reading private local data.
        origin = request.headers.get("origin")
        if origin and origin != f"{request.url.scheme}://{request.url.netloc}":
            return Response(status_code=403)
        if request.headers.get("sec-fetch-site") == "cross-site":
            return Response(status_code=403)
        response = await call_next(request)
        response.headers.update({
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
            "Cross-Origin-Resource-Policy": "same-origin",
            "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; worker-src 'self' blob:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'",
        })
        return response

    def guarded(function, *args):
        try:
            return function(*args)
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        except (ValueError, KeyError, TypeError, OSError) as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/api/catalog")
    def catalog():
        return guarded(workspace.catalog)

    @app.get("/api/gpx/{source_id}")
    def gpx(source_id: str):
        source, body = guarded(workspace.source, source_id)
        return Response(body, media_type="application/gpx+xml", headers={"X-Source-Sha256": source.sha256})

    @app.get("/api/checkpoints/{source_id}")
    def checkpoints(source_id: str):
        return guarded(workspace.checkpoints, source_id)

    @app.get("/api/terrain")
    def terrain():
        return workspace.terrain()

    @app.get("/api/terrain-mesh")
    def terrain_mesh():
        return guarded(build_display_mesh, workspace)

    @app.get("/api/elevation")
    def elevation(lon: float, lat: float):
        return guarded(sample_prepared_elevation, workspace, lon, lat)

    @app.get("/api/terrain/{z}/{x}/{y}.png")
    def tile(z: int, x: int, y: int):
        body, sha = guarded(workspace.tile, z, x, y)
        return Response(body, media_type="image/png", headers={"X-Source-Sha256": sha})

    @app.get("/")
    def page():
        return FileResponse(ROOT / "docs/admin/experiments/gpx-3d/index.html")

    @app.get("/favicon.ico")
    def favicon():
        return Response(status_code=204)

    app.mount("/assets", StaticFiles(directory=ROOT / "docs/admin/experiments/gpx-3d"))
    return app


def main() -> None:
    import uvicorn

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True, help="Only this explicitly selected Workspace is readable")
    parser.add_argument("--port", type=int, default=9127)
    args = parser.parse_args()
    if args.port in {8000, 8080, 9099}:
        parser.error("Use a separate experiment port, e.g. 9127")
    uvicorn.run(create_app(args.project_root), host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
