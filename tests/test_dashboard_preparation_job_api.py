from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

import admin_api
from dashboard_preparation_jobs import DashboardPreparationJobConflict


class JobManagerSpy:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.conflict = False
        self.job = {
            "job_id": "prep." + "a" * 32,
            "project_id": "golden_new",
            "status": "queued",
            "stage": "import",
            "workspace_available": False,
            "can_resume": False,
        }

    def submit_import(self, request, **kwargs):
        self.calls.append(("import", request, kwargs))
        if self.conflict:
            raise DashboardPreparationJobConflict("source_changed", "Source changed; saved job preserved")
        return self.job

    def submit_clone(self, request, **kwargs):
        self.calls.append(("clone", request, kwargs))
        return self.job

    def list(self, project_id=None):
        self.calls.append(("list", project_id))
        return {"jobs": [self.job]}

    def get(self, job_id):
        self.calls.append(("get", job_id))
        if job_id != self.job["job_id"]:
            raise FileNotFoundError(job_id)
        return self.job

    def resume(self, job_id):
        self.calls.append(("resume", job_id))
        return {**self.job, "status": "running"}


@pytest.fixture
def api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    manager = JobManagerSpy()
    workspace = tmp_path / "workspaces"
    source = workspace / "golden_source"
    source.mkdir(parents=True)
    (source / "project.json").write_text(json.dumps({"project_id": source.name}))
    monkeypatch.setattr(admin_api, "DashboardPreparationJobManager", lambda root: manager)
    monkeypatch.setattr(
        admin_api, "list_pretrip_admin_projects",
        lambda **kwargs: [{"project_id": source.name, "name": source.name}],
    )
    # The API test does not load the operator's provider environment.
    monkeypatch.setattr(
        admin_api, "load_scout_env_files",
        lambda **kwargs: None,
    )
    app = FastAPI()
    app.include_router(admin_api.create_admin_router(pretrip_workspace_root=workspace))
    with TestClient(app) as client:
        yield client, manager, workspace


def _import_payload() -> dict:
    return {
        "golden_route_gpx": "/test/raw/golden.gpx",
        "reference_gpx_paths": ["/test/raw/ref.gpx"],
        "dtm_dirs": ["/test/raw/dem"],
        "confirm_import": True,
        "confirm_prepare": True,
        "idempotency_key": "operator-import-1",
        "preparation": {
            "network_mode": "no-network",
            "allow_network_fetch": False,
            "seed_imagery_cache": False,
            "route_corridor_m": 500,
        },
    }


def test_import_submission_is_202_and_preserves_source_and_network_choices(api) -> None:
    client, manager, workspace = api
    response = client.post("/admin/pretrip/projects/golden_new/import-and-prepare", json=_import_payload())
    assert response.status_code == 202
    assert response.json()["status"] == "queued"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-scout-runtime-safety-truth"] == "false"
    kind, request, options = manager.calls[0]
    assert kind == "import"
    assert request.workspace_root == workspace
    assert request.primary_gpx == Path("/test/raw/golden.gpx")
    assert request.dtm_dirs == (Path("/test/raw/dem"),)
    assert request.overwrite is False
    assert request.resolve_default_material_root is False
    assert options["idempotency_key"] == "operator-import-1"
    assert options["preparation_options"]["allow_network_fetch"] is False
    assert options["preparation_options"]["seed_imagery_cache"] is False
    assert not (workspace / "golden_new").exists()


@pytest.mark.parametrize("change,code", [
    ({"confirm_import": False}, 400),
    ({"confirm_prepare": False}, 400),
    ({"overwrite": True}, 409),
    ({"workspace_root": "/outside"}, 422),
    ({"preparation": {"workspace_root": "/outside"}}, 422),
])
def test_import_rejects_unconfirmed_or_rebound_target_before_job_submission(api, change, code) -> None:
    client, manager, _workspace = api
    response = client.post("/admin/pretrip/projects/golden_new/import-and-prepare", json={**_import_payload(), **change})
    assert response.status_code == code
    assert manager.calls == []


def test_saved_job_read_does_not_resume_and_resume_requires_explicit_post(api) -> None:
    client, manager, _workspace = api
    job_id = manager.job["job_id"]
    assert client.get("/admin/dashboard/preparation-jobs").status_code == 200
    assert client.get(f"/admin/dashboard/preparation-jobs/{job_id}").status_code == 200
    assert [row[0] for row in manager.calls] == ["list", "get"]
    path = f"/admin/dashboard/preparation-jobs/{job_id}/resume"
    assert client.post(path, json={"confirm_resume": False}).status_code == 400
    assert [row[0] for row in manager.calls] == ["list", "get"]
    assert client.post(path, json={"confirm_resume": True}).status_code == 202
    assert manager.calls[-1] == ("resume", job_id)
    assert client.get("/admin/dashboard/preparation-jobs/missing").status_code == 404


def test_source_conflict_is_409_instead_of_success(api) -> None:
    client, manager, _workspace = api
    manager.conflict = True
    response = client.post("/admin/pretrip/projects/golden_new/import-and-prepare", json=_import_payload())
    assert response.status_code == 409
    assert "Source changed" in response.json()["detail"]


def test_clone_submission_uses_resolved_source_and_returns_durable_job(api) -> None:
    client, manager, workspace = api
    path = "/admin/dashboard/workspaces/golden_source/clone-jobs"
    payload = {"target_project_id": "golden_new", "idempotency_key": "clone-1"}
    assert client.post(path, json=payload).status_code == 400
    assert manager.calls == []
    response = client.post(path, json={**payload, "confirm_clone": True})
    assert response.status_code == 202
    kind, request, options = manager.calls[0]
    assert kind == "clone"
    assert request.source_project_root == workspace / "golden_source"
    assert request.target_project_id == "golden_new"
    assert options["idempotency_key"] == "clone-1"
