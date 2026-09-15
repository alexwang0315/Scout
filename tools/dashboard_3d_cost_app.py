"""Read-only Dashboard source replay for layer/synchronization profiling."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import HTTPException  # noqa: E402
from fastapi.responses import FileResponse, HTMLResponse, Response  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from navigation_terrain_projection_store import inspect_navigation_terrain_projection  # noqa: E402
from scout_gpx_3d import Gpx3DWorkspace, local_ref  # noqa: E402
from tools.scout_gpx_3d_app import create_app  # noqa: E402


def create_cost_app(project_root: Path, evidence_dir: Path):
    root = project_root.resolve()
    workspace = Gpx3DWorkspace(root)
    app = create_app(root)
    hashes: dict[str, str] = {}

    def read(path: Path) -> bytes:
        body = path.read_bytes()
        hashes[str(path)] = hashlib.sha256(body).hexdigest()
        return body

    project = json.loads(read(root / "project.json"))
    projection_ref = project.get("navigation_terrain_projection_ref")
    if not projection_ref:
        raise ValueError("An existing Workspace projection is required; never compile here")
    snapshot = json.loads(read(local_ref(root, projection_ref)))
    if snapshot.get("boundary", {}).get("candidate_only") is not True or snapshot["boundary"].get("runtime_safety_truth") is not False:
        raise ValueError("Replay requires the existing candidate-only boundary")
    current = inspect_navigation_terrain_projection(root, project, project_id=root.name).payload
    dem = workspace.terrain()
    if dem.get("status") != "ready":
        raise ValueError("Complete prepared terrain is required")
    read(local_ref(root, project["navigation_terrain_dem_manifest_ref"]))
    dem_bytes = {}
    for tile in dem["tiles"]:
        body = read(local_ref(root, tile["source_ref"]))
        if hashlib.sha256(body).hexdigest() != tile["sha256"]:
            raise ValueError("DEM fingerprint changed")
        dem_bytes[(tile["z"], tile["x"], tile["y"])] = body
    snapshot["terrain_raster_dem"] = {**dem, "tile_url_template": "/cost-dem/{z}/{x}/{y}.png"}
    qgis = None
    run_id = project.get("qgis_terrain_preparation_workflow_run_id")
    if run_id:
        qgis = json.loads(read(local_ref(root, f"outputs/spatial/qgis/{run_id}/workflow_run.json")))
        if qgis.get("candidate_only") is not True or qgis.get("runtime_safety_truth") is not False:
            raise ValueError("QGIS source must remain candidate-only")

    # Complete prepared Rudy cache, with an explicit zoom cap in the replay.
    # Native higher-zoom coverage is partial; never fill gaps or fetch here.
    cache = root / "cache/raster-tiles" / root.name / "rudy-twmap"
    cache_manifest_ref = f"outputs/layers/manifests/{root.name}.rudy-twmap.raster_tile_cache_manifest.json"
    cache_manifest = json.loads(read(local_ref(root, cache_manifest_ref)))
    if cache_manifest.get("imagery_source_id") != "happyman_rudy_twmap":
        raise ValueError("Rudy cache provider mismatch")
    rudy_bytes = {}
    for path in cache.glob("*/*/*.png"):
        z, x, leaf = path.relative_to(cache).parts
        rudy_bytes[(int(z), int(x), int(Path(leaf).stem))] = read(path)

    source = read(ROOT / "docs/admin/scout-dashboard-v0.1.html").decode()
    scripts = list(re.finditer(r"<script>\s*([\s\S]*?)</script>", source))
    if len(scripts) != 1:
        raise ValueError("Dashboard inline script structure changed")
    script = scripts[0].group(1)
    bootstrap = 'document.addEventListener("DOMContentLoaded", () => {'
    if script.count(bootstrap) != 1:
        raise ValueError("Dashboard bootstrap hook changed")
    # Preserve all implementation functions; suppress only normal API/bootstrap effects.
    script = script.replace(bootstrap, 'document.addEventListener("cost-replay-no-bootstrap", () => {', 1)
    html = source[:scripts[0].start()] + '<script src="/cost-dashboard-source.js"></script><script src="/dashboard-cost/harness.js"></script>' + source[scripts[0].end():]
    html = html.replace("</head>", '<link rel="stylesheet" href="/dashboard-cost/style.css"></head>')
    read(ROOT / "docs/admin/scout-maplibre-evidence.js")
    for path in (ROOT / "docs/admin/vendor/maplibre-gl/6.2.0").iterdir():
        if path.is_file():
            read(path)
    payload = {
        "project": project, "snapshot": snapshot, "qgis": qgis,
        "provenance": {
            "kind": "existing_workspace_projection_replay", "projection_ref": projection_ref,
            "projection_compilation": snapshot.get("projection_compilation"),
            "current_read_interface_status": current.get("status"),
            "current_read_interface_detail": current.get("projection_state"),
            "dem_fingerprint": dem["source_fingerprint"], "dem_tiles": len(dem_bytes),
            "cached_rudy_tiles": len(rudy_bytes), "source_hashes": hashes,
            "rudy_maxzoom": cache_manifest["plan"]["max_zoom"],
            "rudy_mode": "existing_prepared_cache_with_explicit_zoom_cap",
            "authority": {"visualization_only": True, "candidate_only": True, "runtime_safety_truth": False},
        },
    }
    payload_bytes = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    evidence_dir.mkdir(parents=True, exist_ok=True)
    (evidence_dir / "replay-source.json").write_text(json.dumps({
        "payload_sha256": hashlib.sha256(payload_bytes).hexdigest(),
        **payload["provenance"],
    }, ensure_ascii=False, indent=2) + "\n")

    @app.get("/dashboard-cost")
    def page():
        return HTMLResponse(html)

    @app.get("/cost-dashboard-source.js")
    def dashboard_script():
        return Response(script, media_type="text/javascript")

    @app.get("/cost-data")
    def data():
        return Response(payload_bytes, media_type="application/json", headers={"X-Source-Sha256": hashlib.sha256(payload_bytes).hexdigest()})

    @app.get("/cost-dem/{z}/{x}/{y}.png")
    def terrain(z: int, x: int, y: int):
        body = dem_bytes.get((z, x, y))
        if body is None:
            raise HTTPException(404, "DEM outside pinned evidence")
        return Response(body, media_type="image/png")

    @app.get("/admin/tiles/imagery/{project_id}/imagery/{z}/{x}/{y}.png")
    def rudy(project_id: str, z: int, x: int, y: int):
        body = rudy_bytes.get((z, x, y)) if project_id == root.name else None
        if body is None:
            raise HTTPException(404, "Rudy tile not in local cache; network disabled")
        return Response(body, media_type="image/png")

    @app.get("/admin/scout-maplibre-evidence.js")
    def shared_map_helper():
        return FileResponse(ROOT / "docs/admin/scout-maplibre-evidence.js")

    app.mount("/admin/vendor/maplibre-gl/6.2.0", StaticFiles(directory=ROOT / "docs/admin/vendor/maplibre-gl/6.2.0"))
    app.mount("/dashboard-cost", StaticFiles(directory=ROOT / "docs/admin/experiments/dashboard-3d-cost"))
    return app


if __name__ == "__main__":
    import uvicorn

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--port", type=int, default=9129)
    args = parser.parse_args()
    if args.port in {8000, 8080, 9099, 9127, 9128}:
        parser.error("Use a separate local test port, e.g. 9129")
    if args.evidence_dir.resolve().is_relative_to(args.project_root.resolve()):
        parser.error("Evidence must not be written inside the source Workspace")
    uvicorn.run(create_cost_app(args.project_root, args.evidence_dir), host="127.0.0.1", port=args.port, log_level="warning")
