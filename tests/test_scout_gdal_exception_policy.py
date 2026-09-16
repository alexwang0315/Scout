"""Fresh-process regression for Scout's explicit, local GDAL error policy."""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import warnings

import pytest

CASES = [
    "transform_ok", "transform_invalid_crs", "transform_invalid_native_crs", "transform_nonfinite",
    "native_ok", "native_nodata", "native_bad_crs", "native_open_failure",
    "native_warp_failure", "native_rasterize_failure",
    "sample_ok", "sample_bad_crs", "sample_open_failure", "sample_invalid_grid",
]


def _states():
    from osgeo import gdal, ogr, osr
    return {name: {"use": module.GetUseExceptions(), "local": module._GetExceptionsLocal()}
            for name, module in (("gdal", gdal), ("ogr", ogr), ("osr", osr))}


def _raster(path, *, projection=3826, sample=False, nodata=False, invalid_grid=False):
    import numpy as np
    from osgeo import gdal, osr
    from pretrip_source_ingest import wgs84_to_twd97
    with gdal.ExceptionMgr(useExceptions=False), osr.ExceptionMgr(useExceptions=False):
        if sample:
            x, y = wgs84_to_twd97(24, 121)
            transform = (x - 50, 20, 0, y + 50, 0, -20)
        else:
            transform = (280000, 20, 0, 2660000, 0, -20)
        if invalid_grid:
            transform = (*transform[:2], 1, *transform[3:])
        data = np.full((5, 5), 713, dtype="float32")
        if nodata:
            data[1 if sample else 2, 2] = -9999
        dataset = gdal.GetDriverByName("GTiff").Create(str(path), 5, 5, 1, gdal.GDT_Float32)
        srs = osr.SpatialReference()
        assert srs.ImportFromEPSG(projection) == 0
        dataset.SetProjection(srs.ExportToWkt())
        dataset.SetGeoTransform(transform)
        dataset.GetRasterBand(1).SetNoDataValue(-9999)
        dataset.GetRasterBand(1).WriteArray(data)
        dataset.FlushCache()
        dataset = None
    return path


def _native_inputs(directory, case):
    import scout_exploration_workspace as workspace
    directory.mkdir(parents=True, exist_ok=True)
    root = directory / "fixture"
    root.mkdir()
    intake = root / workspace.INTAKE_REF
    intake.parent.mkdir(parents=True)
    intake.write_text('{"fixture":true}')
    raster = directory / "native.tif"
    if case != "native_open_failure":
        _raster(raster, projection=3857 if case == "native_bad_crs" else 3826,
                nodata=case == "native_nodata")
    raw = {
        "raster_sources": [{"path": str(raster), "source_resolution_m": 20, "crs": "EPSG:3826"}],
        "candidate_tiles": [],
        "aoi_bbox_twd97": {"min_x": 280020, "min_y": 2659920, "max_x": 280080, "max_y": 2659980},
        "aoi_polygon_twd97": [[280020, 2659920], [280080, 2659920], [280080, 2659980],
                             [280020, 2659980], [280020, 2659920]],
        "external_source_bindings": [{"path": str(raster), "sha256":
            hashlib.sha256(raster.read_bytes()).hexdigest() if raster.exists() else "0" * 64}],
    }
    return workspace, root, raw


def _run_native(directory, case):
    from osgeo import gdal
    workspace, root, raw = _native_inputs(directory, case)
    expected = {
        "native_bad_crs": "Raw raster CRS disagrees with the declared TWD97 CRS",
        "native_open_failure": "Raw DEM is unreadable by GDAL",
        "native_warp_failure": "Native GDAL AOI crop failed",
        "native_rasterize_failure": "AOI mask could not be rasterized",
    }
    with pytest.MonkeyPatch.context() as patch:
        if case == "native_warp_failure":
            patch.setattr(gdal, "Warp", lambda *a, **k: None)
        if case == "native_rasterize_failure":
            patch.setattr(gdal, "RasterizeLayer", lambda *a, **k: 1)
        if case in expected:
            with pytest.raises(workspace.ExplorationWorkspaceError, match=expected[case]):
                workspace.prepare_native_aoi_dem(root, None, "outputs/native", raw)
            return {"error_type": "ExplorationWorkspaceError", "message": expected[case]}
        result = workspace.prepare_native_aoi_dem(root, None, "outputs/native", raw)
    assert result["status"] == ("partial" if case == "native_nodata" else "completed")
    assert result["aoi_cell_count"] == 9
    assert result["finite_cell_count"] == (8 if case == "native_nodata" else 9)
    assert result["nodata_cell_count"] == (1 if case == "native_nodata" else 0)
    assert result["candidate_only"] is True and result["runtime_safety_truth"] is False
    return result


def _run_sample(directory, case):
    import scout_planned_preparation as preparation
    path = directory / "sample.tif"
    if case != "sample_open_failure":
        _raster(path, sample=True, nodata=True,
                projection=3857 if case == "sample_bad_crs" else 3826,
                invalid_grid=case == "sample_invalid_grid")
    expected = {
        "sample_bad_crs": "Prepared DEM CRS is not verified EPSG:3826",
        "sample_open_failure": "Prepared DEM is unreadable",
        "sample_invalid_grid": "Prepared DEM uses an unsupported native grid",
    }
    points = [{"lat": 24, "lon": 121}, {"lat": 24.00018, "lon": 121},
              {"lat": 24, "lon": 121}, {"lat": 24.1, "lon": 121}]
    with pytest.MonkeyPatch.context() as patch:
        # Exercise the existing GDAL fallback even when rasterio is installed.
        patch.setitem(sys.modules, "rasterio", None)
        if case in expected:
            with pytest.raises(preparation.PlannedPreparationError, match=expected[case]):
                preparation._sample_dem(path, points)
            return {"error_type": "PlannedPreparationError", "message": expected[case]}
        result = preparation._sample_dem(path, points)
    assert result["values"] == [713, None, 713, None]
    assert result["resolution_m"] == [20, 20] and result["interpolated"] is False
    return result


def _run_transform(case):
    from osgeo import osr
    from pydantic import ValidationError
    from scout_exploration_models import ExplorationPoint, _transform
    if case == "transform_invalid_crs":
        with pytest.raises(ValidationError, match="Input should be"):
            ExplorationPoint(x=280200, y=2658500, crs="EPSG:999999")
        return {"error_type": "ValidationError"}
    if case == "transform_invalid_native_crs":
        # This private helper previously surfaces a GDAL TypeError for an
        # unresolvable native CRS. Keep that behavior; public CRS validation
        # remains the separate ValidationError case above.
        with pytest.raises(TypeError, match="CoordinateTransformation_TransformPoint"):
            _transform(280200, 2658500, "EPSG:999999", "EPSG:4326")
        return {"error_type": "TypeError", "message_contains": "CoordinateTransformation_TransformPoint"}
    if case == "transform_nonfinite":
        class FailedTransform:
            def TransformPoint(self, x, y):
                return float("inf"), float("inf"), 0
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(osr, "CoordinateTransformation", lambda *a: FailedTransform())
            with pytest.raises(ValueError, match="^Coordinate transform failed$"):
                _transform(280200, 2658500, "EPSG:3826", "EPSG:4326")
        return {"error_type": "ValueError", "message": "Coordinate transform failed"}
    point = ExplorationPoint(x=280200, y=2658500, crs="EPSG:3826")
    lon, lat = point.wgs84()
    x, y = _transform(lon, lat, "EPSG:4326", "EPSG:3826")
    assert x == pytest.approx(point.x, abs=0.03)
    assert y == pytest.approx(point.y, abs=0.03)
    assert _transform(x, y, "EPSG:3826", "EPSG:3826") == (x, y)
    return {"roundtrip_m": [x - point.x, y - point.y]}


def _run_concurrent(directory, kind):
    from osgeo import gdal, ogr, osr
    from scout_exploration_models import _transform
    entered, observed = threading.Event(), threading.Event()
    evidence, errors = {}, []
    native = _native_inputs(directory, "native_ok") if kind == "native" else None
    original = gdal.Warp if kind == "native" else osr.CoordinateTransformation

    def intercept(*args, **kwargs):
        current = _states()
        expected = {"gdal": 0, "ogr": 0, "osr": 0} if kind == "native" else {"gdal": 1, "ogr": 1, "osr": 0}
        assert {k: v["use"] for k, v in current.items()} == expected
        evidence["owned_inside"] = current
        entered.set()
        assert observed.wait(10), "Other thread did not observe its policy"
        return original(*args, **kwargs)

    def owner():
        try:
            with gdal.ExceptionMgr(True), ogr.ExceptionMgr(True), osr.ExceptionMgr(True):
                before = _states()
                if native:
                    workspace, root, raw = native
                    result = workspace.prepare_native_aoi_dem(root, None, "outputs/native", raw)
                    assert result["finite_cell_count"] == 9
                else:
                    _transform(280200, 2658500, "EPSG:3826", "EPSG:4326")
                assert _states() == before
                evidence["owned_restored"] = _states()
        except BaseException as error:
            errors.append(error)
            entered.set()

    def observer():
        try:
            with gdal.ExceptionMgr(True), ogr.ExceptionMgr(True), osr.ExceptionMgr(True):
                before = _states()
                assert entered.wait(10)
                assert _states() == before
                evidence["other_thread"] = _states()
        except BaseException as error:
            errors.append(error)
        finally:
            observed.set()

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(gdal if kind == "native" else osr,
                      "Warp" if kind == "native" else "CoordinateTransformation", intercept)
        threads = [threading.Thread(target=owner), threading.Thread(target=observer)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(15)
        assert not any(thread.is_alive() for thread in threads)
    if errors:
        raise errors[0]
    return evidence


def _child(case, mode, directory):
    from osgeo import gdal, ogr, osr
    warnings.simplefilter("error", FutureWarning)
    initial = _states()
    directory.mkdir(parents=True, exist_ok=True)
    with contextlib.ExitStack() as stack:
        if mode == "enabled":
            for module in (gdal, ogr, osr):
                stack.enter_context(module.ExceptionMgr(useExceptions=True))
        before = _states()
        if case.startswith("concurrent_"):
            result = _run_concurrent(directory, case.split("_", 1)[1])
        elif case.startswith("native_"):
            result = _run_native(directory, case)
        elif case.startswith("sample_"):
            result = _run_sample(directory, case)
        else:
            result = _run_transform(case)
        after = _states()
        assert after == before, {"before": before, "after": after}
    assert _states() == initial
    print(json.dumps({"case": case, "outer_policy": mode, "before": before, "after": after,
                      "initial_restored": _states(), "result": result}, sort_keys=True))


def _invoke(case, mode, tmp_path):
    root = Path(os.environ.get("SCOUT_GDAL_POLICY_REPLAY_ROOT", Path(__file__).resolve().parents[1]))
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    child = subprocess.run([sys.executable, "-B", str(Path(__file__).resolve()), "--replay",
                            str(root), case, mode, str(tmp_path / case)],
                           cwd=root, env=env, capture_output=True, text=True, timeout=45)
    assert child.returncode == 0, child.stdout + child.stderr
    receipt = json.loads(child.stdout)
    assert receipt["case"] == case
    assert "Warning" not in child.stderr, child.stderr
    return receipt


@pytest.mark.parametrize("case", CASES)
@pytest.mark.parametrize("mode", ["unset", "enabled"])
def test_gdal_policy_fresh_process(case, mode, tmp_path):
    _invoke(case, mode, tmp_path)


@pytest.mark.parametrize("case", ["concurrent_transform", "concurrent_native"])
def test_gdal_policy_does_not_escape_to_another_thread(case, tmp_path):
    _invoke(case, "unset", tmp_path)


if __name__ == "__main__":
    assert sys.argv[1] == "--replay"
    sys.path.insert(0, sys.argv[2])
    _child(sys.argv[3], sys.argv[4], Path(sys.argv[5]))
