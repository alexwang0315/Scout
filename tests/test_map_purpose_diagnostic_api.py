from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import admin_api


@pytest.mark.parametrize("exists", [True, False])
def test_map_purpose_script_is_same_origin_uncached_or_explicitly_missing(
    tmp_path: Path, monkeypatch, exists: bool
) -> None:
    script = tmp_path / "scout-map-purpose-diagnostic.js"
    contents = "window.ScoutMapPurposeDiagnostic = {fixture: true};\n"
    if exists:
        script.write_text(contents)
    monkeypatch.setattr(admin_api, "DEFAULT_MAP_PURPOSE_DIAGNOSTIC_SCRIPT", script)
    monkeypatch.setattr(admin_api, "load_scout_env_files", lambda **kwargs: None)
    app = FastAPI()
    app.include_router(admin_api.create_admin_router(pretrip_workspace_root=tmp_path))
    response = TestClient(app).get("/admin/scout-map-purpose-diagnostic.js")
    if exists:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/javascript")
        assert response.headers["cache-control"] == "no-store"
        assert response.text == contents
    else:
        assert response.status_code == 404
        assert response.json()["detail"] == "Map purpose diagnostic not found"
