"""Isolated read-only benchmark host; never starts the Dashboard runtime."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.responses import FileResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from tools.scout_gpx_3d_app import create_app  # noqa: E402


def create_benchmark_app(project_root: Path):
    app = create_app(project_root)

    @app.get("/benchmark")
    def benchmark():
        return FileResponse(ROOT / "docs/admin/experiments/gpx-3d/benchmark/index.html")

    app.mount("/benchmark-maplibre", StaticFiles(directory=ROOT / "docs/admin/vendor/maplibre-gl/6.2.0"))
    return app


if __name__ == "__main__":
    import uvicorn

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--port", type=int, default=9128)
    args = parser.parse_args()
    if args.port in {8000, 8080, 9099, 9127}:
        parser.error("Use a separate benchmark port, e.g. 9128")
    uvicorn.run(create_benchmark_app(args.project_root), host="127.0.0.1", port=args.port, log_level="warning")
