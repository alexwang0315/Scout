from __future__ import annotations

import gzip
import hashlib
import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cwa_precipitation_grid import parse_qpesums_grid
import pytest

from weather_grid_store import WeatherGridStore, load_weather_grid_snapshot


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "cwa" / "qpesums"


def _grid(dataset_id: str):
    payload = json.loads((FIXTURE_ROOT / f"{dataset_id}.small.json").read_text())
    return parse_qpesums_grid(
        payload,
        fetched_at="2026-07-13T10:42:00+08:00",
        coordinate_transformer=lambda lat, lon: (lat, lon),
    )


def test_weather_grid_store_is_content_addressed_deduplicated_and_cache_explicit(
    tmp_path: Path,
) -> None:
    store = WeatherGridStore(tmp_path / "rainfall")
    first = store.put(_grid("O-B0045-001"))
    second = store.put(_grid("O-B0045-001"))

    assert first == second
    assert first.suffixes == [".json", ".gz"]
    assert first.is_file()
    with gzip.open(first, "rt", encoding="utf-8") as handle:
        frame = json.load(handle)
    assert frame["grid"]["values"][1] == [1.0, 2.0, None]
    assert frame["cachePolicy"]["cacheable"] is False
    assert frame["cachePolicy"]["mustRefetchOnPrepare"] is True

    manifest = store.update_manifest([_grid("O-B0045-001"), _grid("F-B0046-001")])
    assert manifest["latestByKind"]["qpe_past_1h"]["datasetId"] == "O-B0045-001"
    assert manifest["latestByKind"]["qpf_next_1h"]["datasetId"] == "F-B0046-001"
    assert manifest["boundary"]["raspberryPiGridProcessing"] is False
    assert (store.root / "rainfall_grid_manifest.json").is_file()


def test_public_manifest_redacts_full_grid_and_internal_paths(tmp_path: Path) -> None:
    store = WeatherGridStore(tmp_path / "rainfall")
    store.update_manifest([_grid("O-B0045-001"), _grid("F-B0046-001")])

    public = store.public_manifest()
    serialized = json.dumps(public)
    assert "values" not in serialized
    assert ".json.gz" not in serialized
    assert str(tmp_path) not in serialized
    assert public["products"][0]["unit"] == "mm"


def test_refetch_dedup_manifest_metadata_matches_stored_snapshot(tmp_path: Path) -> None:
    store = WeatherGridStore(tmp_path / "rainfall")
    original = _grid("O-B0045-001")
    later = original.model_copy(
        update={
            "fetched_at": original.fetched_at + timedelta(minutes=10),
            "data_delay_minutes": original.data_delay_minutes + 10,
        }
    )

    original_path = store.put(original)
    later_path = store.put(later)
    manifest = store.update_manifest([later])

    assert later_path == original_path
    assert manifest["latestByKind"]["qpe_past_1h"]["fetchedAt"] == (
        original.fetched_at.isoformat()
    )


def test_snapshot_loader_rejects_filename_content_hash_mismatch(tmp_path: Path) -> None:
    store = WeatherGridStore(tmp_path / "rainfall")
    path = store.put(_grid("O-B0045-001"))
    tampered_name = path.with_name("20260713T103000+0800-0000000000000000.json.gz")
    shutil.copyfile(path, tampered_name)

    with pytest.raises(ValueError, match="content hash"):
        load_weather_grid_snapshot(tampered_name)


def test_public_manifest_does_not_report_ready_with_only_one_product(
    tmp_path: Path,
) -> None:
    store = WeatherGridStore(tmp_path / "rainfall")
    store.update_manifest([_grid("O-B0045-001")])

    public = store.public_manifest(
        evaluated_at=datetime(2026, 7, 13, 3, 40, tzinfo=timezone.utc)
    )

    assert [item["gridKind"] for item in public["products"]] == ["qpe_past_1h"]
    assert public["products"][0]["freshness"]["status"] == "current"
    assert public["status"] != "ready"


def test_public_manifest_rejects_pair_source_frames_that_are_not_active(
    tmp_path: Path,
) -> None:
    store = WeatherGridStore(tmp_path / "rainfall")
    grids = [_grid("O-B0045-001"), _grid("F-B0046-001")]
    initial = store.update_manifest(grids)
    source_frame_ids = {
        kind: frame["frameId"] for kind, frame in initial["latestByKind"].items()
    }
    identity = {
        "projectId": "fixture-route",
        "routeRef": "outputs/segment_display_geometry.json",
        "routeSha256": "a" * 64,
        "routeBasis": "segment_display_geometry",
        "sourceFrameIds": source_frame_ids,
    }
    pair_id = "cwa.rainfall.pair." + hashlib.sha256(
        json.dumps(
            identity,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    store.update_manifest(grids, provenance={**identity, "pairId": pair_id})
    manifest_path = store.root / "rainfall_grid_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["sourceFrameIds"]["qpe_past_1h"] = "tampered-frame"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="active source frames"):
        store.public_manifest()
