"""Opt-in local target/Decision browser fixture; never a qualification baseline."""

from __future__ import annotations

import argparse
import json
import re
import runpy
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def fixture_app(workspace: Path, output: Path) -> FastAPI:
    from admin_api import create_admin_app
    from cwa_precipitation_grid import parse_qpesums_grid
    from weather_grid_store import WeatherGridStore

    prepare = runpy.run_path(str(ROOT / "tests/test_admin_cwa_precipitation_grid.py"))["_prepare_workspace"]
    workspace_root = prepare(workspace)
    project_root = workspace_root / "fixture-route"
    project_path = project_root / "project.json"
    project = json.loads(project_path.read_text())
    now = datetime.now(timezone.utc).replace(microsecond=0)
    source = now - timedelta(minutes=5)
    grids = []
    for dataset, values in (
        ("O-B0045-001", ((6.0, 12.0, 4.0), (10.0, 0.0, None))),
        ("F-B0046-001", ((12.0, 24.0, 4.0), (37.6, None, None))),
    ):
        payload = json.loads((ROOT / f"tests/fixtures/cwa/qpesums/{dataset}.small.json").read_text())
        grid = parse_qpesums_grid(payload, fetched_at=now, coordinate_transformer=lambda lat, lon: (lat, lon))
        grids.append(grid.model_copy(update={
            "source_timestamp": source, "fetched_at": now,
            "valid_from": source - timedelta(hours=1) if dataset.startswith("O-") else source,
            "valid_until": source if dataset.startswith("O-") else source + timedelta(hours=1),
            "data_delay_minutes": 5, "values": values,
        }))
    rainfall_root = project_root / "outputs/environment/cwa/rainfall"
    manifest = WeatherGridStore(rainfall_root).update_manifest(grids)
    for field, kind in (("cwa_qpe_numeric_grid_ref", "qpe_past_1h"), ("cwa_qpf_numeric_grid_ref", "qpf_next_1h")):
        project[field] = "outputs/environment/cwa/rainfall/" + manifest["latestByKind"][kind]["dataRef"]
    project_path.write_text(json.dumps(project))
    backend = create_admin_app(pretrip_workspace_root=workspace_root, now_factory=lambda: now)
    app = FastAPI()
    events: list[dict] = []
    output.parent.mkdir(parents=True, exist_ok=True)

    def receipt() -> dict:
        return {
            "mode": "synthetic_target_browser_fixture",
            "official_qualification_eligible": False,
            "actualCwaRefreshPerformed": False,
            "realLocationAccessed": False, "rfSendPerformed": False,
            "events": events,
        }

    @app.middleware("http")
    async def restrict_requests(request: Request, call_next):
        path = request.url.path
        allowed_post = path in {
            "/admin/pretrip/projects/fixture-route/rainfall-location-approvals",
            "/admin/pretrip/projects/fixture-route/rainfall-trend",
        }
        if request.method not in {"GET", "HEAD"} and not (request.method == "POST" and allowed_post):
            return JSONResponse({"detail": "Fixture forbids this effect"}, status_code=405)
        response = await call_next(request)
        if path.startswith("/admin/pretrip/projects/"):
            events.append({"method": request.method, "path": path, "status": response.status_code})
            output.write_text(json.dumps(receipt(), indent=2))
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = "default-src 'self' data: blob:; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self'"
        return response

    @app.get("/fixture-evidence")
    def evidence():
        return receipt()

    @app.get("/admin/pretrip/projects/fixture-route/connected-preparation")
    def idle_preparation():
        return {"projectId": "fixture-route", "status": "idle", "runCount": 0}

    @app.get("/admin/dashboard", response_class=HTMLResponse)
    def dashboard(request: Request):
        html = (ROOT / "docs/admin/scout-dashboard-v0.1.html").read_text()
        bootstrap = r'''
    document.addEventListener("DOMContentLoaded", async () => {
      state.route = "outdoor-weather";
      state.project = {project_id: "fixture-route", checkpoints: [
        {candidate_id: "CP-02", label: "CP 02", lat: 23.0125, lon: 121.025},
        {candidate_id: "CP-103", label: "CP 103", lat: 23.0, lon: 121.0125},
      ]};
      state.weatherTargetCheckpointId = "CP-02";
      const banner = document.createElement("p");
      banner.textContent = "SYNTHETIC FIXTURE - no real location / CWA fetch / RF";
      banner.style.cssText = "position:sticky;top:0;background:#fff;color:#111;z-index:9999;padding:8px;margin:0";
      document.body.prepend(banner);
      Object.defineProperty(navigator, "geolocation", {value: {
        getCurrentPosition: resolve => resolve({
          coords: {latitude: 23.0, longitude: 121.0, accuracy: 10}, timestamp: FIXTURE_TIMESTAMP,
        }),
      }});
      renderWeatherIntersectionMap = () => "";
      bindMobileNavigation();
      await loadWeatherData();
    });

    function apiBase() {
'''.replace("FIXTURE_TIMESTAMP", str(int(now.timestamp() * 1000)))
        html, count = re.subn(
            r'    document.addEventListener\("DOMContentLoaded", \(\) => \{.*?    function apiBase\(\) \{',
            lambda _match: bootstrap, html, count=1, flags=re.S,
        )
        if count != 1:
            raise RuntimeError("Dashboard fixture bootstrap boundary moved")
        return HTMLResponse(html)

    app.mount("/", backend)
    return app


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture-harness", action="store_true", required=True)
    parser.add_argument("--port", type=int, default=19107)
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/browser/dashboard-weather-target/evidence.json")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="scout-weather-target-fixture-") as temp:
        app = fixture_app(Path(temp), args.output)
        uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
