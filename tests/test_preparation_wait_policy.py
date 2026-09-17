"""Preparation observes running work until a real terminal state or explicit deadline."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import pretrip_layer_preparation as preparation
from qgis_spatial_contracts import (
    QgisBackendAvailability,
    QgisBackendStatus,
    SpatialAnalysisError,
    SpatialAnalysisErrorCode,
    SpatialWorkflowState,
)


@pytest.mark.parametrize("stage", ["terrain", "route_hypothesis"])
@pytest.mark.parametrize("explicit_deadline", [False, True])
def test_running_work_is_only_cancelled_by_explicit_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: str,
    explicit_deadline: bool,
) -> None:
    project_root = tmp_path / "golden_wait_policy"
    project_root.mkdir()
    (project_root / "project.json").write_text(json.dumps({
        "project_id": project_root.name,
        "terrain_feature_manifest_ref": "outputs/terrain_feature_manifest.json",
        "terrain_dem_route_bbox_raster_ref": "outputs/terrain.tif",
    }))
    calls = {"poll": 0, "cancel": 0}
    ticks = iter(range(0, 1_000_000, 100_000))
    monkeypatch.setattr(preparation.time, "monotonic", lambda: next(ticks))

    class Backend:
        def status(self, **_kwargs):
            return QgisBackendStatus(
                availability=QgisBackendAvailability.AVAILABLE,
                enabled=True, configured=True, endpoint_configured=True,
                reachable=True, qgis_application_available=True,
                plugin_bridge_available=True, capabilities_discoverable=True,
            )

        def start_workflow(self, **_kwargs):
            return SimpleNamespace(
                state=SpatialWorkflowState.RUNNING,
                workflow_run_id="observed-running-work", error=None, warnings=[],
            )

        def get_run(self, **_kwargs):
            calls["poll"] += 1
            run = self.start_workflow()
            if calls["poll"] == 3:
                run.state = SpatialWorkflowState.FAILED
                run.error = SpatialAnalysisError(
                    code=SpatialAnalysisErrorCode.PROCESSING_FAILED,
                    message="Actual terminal failure after useful progress.",
                )
            return run

        def cancel_workflow(self, **_kwargs):
            calls["cancel"] += 1

    options = {"qgis_terrain_workflow_timeout_s": 0.0} if explicit_deadline else {}
    request = preparation.LayerPreparationRequest(
        project_id=project_root.name, project_root=project_root,
        layers=("terrain",), qgis_terrain_poll_interval_s=0.0, **options,
    )
    kwargs = {
        "project_root": project_root,
        "manifest": {"normalized_layers": ["terrain"], "finished_at": "2026-09-09T00:00:00Z"},
        "request": request, "backend": Backend(),
    }
    if stage == "terrain":
        result = preparation._run_qgis_terrain_feature_stack_after_layer_preparation(**kwargs)
    else:
        result = preparation._run_qgis_terrain_route_hypothesis_after_layer_preparation(
            **kwargs, qgis_terrain_feature_stack={"status": "completed"},
        )
    if explicit_deadline:
        assert result["status"] == "timeout"
        assert calls == {"poll": 0, "cancel": 1}
    else:
        assert result["status"] == "failed"
        assert result["error"]["code"] == "PROCESSING_FAILED"
        assert calls == {"poll": 3, "cancel": 0}
    assert result["python_dtm_processing_used"] is False
    assert result["boundary"]["runtime_safety_truth"] is False


@pytest.mark.parametrize("deadline", [None, 86_400.0])
def test_construction_wait_accepts_unbounded_or_explicit_long_deadline(tmp_path, deadline):
    request = preparation.LayerPreparationRequest(
        project_id="golden_wait_policy", project_root=tmp_path,
        qgis_terrain_workflow_timeout_s=deadline,
    )
    preparation._validate_request(request)


@pytest.mark.parametrize("deadline", [-1.0, float("nan"), float("inf")])
def test_invalid_explicit_deadline_is_rejected(tmp_path, deadline):
    request = preparation.LayerPreparationRequest(
        project_id="golden_wait_policy", project_root=tmp_path,
        qgis_terrain_workflow_timeout_s=deadline,
    )
    with pytest.raises(ValueError, match="finite and nonnegative"):
        preparation._validate_request(request)
