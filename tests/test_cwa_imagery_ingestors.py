from pathlib import Path

import pytest

from cwa_imagery_registry import build_cwa_imagery_registry
from cwa_radar_ingestor import (
    CwaRadarIngestor,
    _evenly_spaced,
    _metadata_candidates,
    _sniff_image_media_type,
    _validate_cwa_redirect,
)
from cwa_satellite_ingestor import CwaSatelliteIngestor
from weather_imagery_tile_cache import WeatherImageryTileCache


def _bytes_fetcher(url: str) -> tuple[bytes, str, str | None]:
    assert url.startswith("https://cwaopendata.s3.ap-northeast-1.amazonaws.com/")
    return b"fixture-image", "image/png", "etag-fixture"


def test_radar_ingestor_sorts_deduplicates_and_selects_12h_frames(tmp_path: Path) -> None:
    registry = build_cwa_imagery_registry()
    spec = registry["radar.integrated.taiwan.transparent"]
    cache = WeatherImageryTileCache(tmp_path / "cache")
    history = [
        {"sourceTimestamp": "2026-07-11T03:20:00Z", "url": spec.latest_url},
        {"sourceTimestamp": "2026-07-11T03:10:00Z", "url": spec.latest_url},
        {"sourceTimestamp": "2026-07-11T03:20:00Z", "url": spec.latest_url},
    ]
    ingestor = CwaRadarIngestor(
        registry=registry,
        cache=cache,
        latest_metadata_fetcher=lambda _spec: history[0],
        history_metadata_fetcher=lambda _spec, _hours: history,
        bytes_fetcher=_bytes_fetcher,
    )

    with pytest.raises(PermissionError, match="explicit network approval"):
        ingestor.ingest_latest(spec.product_id)

    frames = ingestor.ingest_recent(
        spec.product_id,
        hours=12,
        allow_network_fetch=True,
        fetched_at="2026-07-11T03:27:00Z",
        dimensions=(4, 4),
        build_display_asset=False,
    )

    assert [item.source_timestamp for item in frames] == [
        "2026-07-11T03:10:00Z",
        "2026-07-11T03:20:00Z",
    ]
    assert all(item.processing_target == "server_side_job" for item in frames)


def test_satellite_ingestor_rejects_radar_product(tmp_path: Path) -> None:
    registry = build_cwa_imagery_registry()
    ingestor = CwaSatelliteIngestor(
        registry=registry,
        cache=WeatherImageryTileCache(tmp_path / "cache"),
        latest_metadata_fetcher=lambda spec: {
            "sourceTimestamp": "2026-07-11T03:20:00Z",
            "url": spec.latest_url,
        },
        history_metadata_fetcher=lambda _spec, _hours: [],
        bytes_fetcher=_bytes_fetcher,
    )

    with pytest.raises(ValueError, match="not a satellite product"):
        ingestor.ingest_latest(
            "radar.integrated.taiwan.transparent",
            allow_network_fetch=True,
        )


def test_cwa_metadata_parser_accepts_sibling_datetime_and_nested_product_url() -> None:
    payload = b'''{
      "dataset": {
        "resource": {"ProductURL": "https://cwaopendata.s3.ap-northeast-1.amazonaws.com/Observation/O-A0058-006.png"},
        "DateTime": "2026-07-11T03:20:00+08:00"
      }
    }'''

    assert _metadata_candidates(payload) == [
        {
            "sourceTimestamp": "2026-07-11T03:20:00+08:00",
            "url": "https://cwaopendata.s3.ap-northeast-1.amazonaws.com/Observation/O-A0058-006.png",
        }
    ]


def test_cwa_metadata_parser_accepts_satellite_datetime_casing() -> None:
    payload = b'''{
      "dataset": {
        "GeoInfo": {
          "LongitudeRange": "115.9-126.1",
          "LatitudeRange": "19.1-28.3"
        },
        "ObsTime": {"Datetime": "2026-07-11T22:10:00+08:00"},
        "Resource": {
          "ProductURL": "https://cwaopendata.s3.ap-northeast-1.amazonaws.com/Observation/O-B0030-003.jpg"
        }
      }
    }'''

    assert _metadata_candidates(payload) == [
        {
            "sourceTimestamp": "2026-07-11T22:10:00+08:00",
            "url": "https://cwaopendata.s3.ap-northeast-1.amazonaws.com/Observation/O-B0030-003.jpg",
            "bboxWgs84": {"west": 115.9, "south": 19.1, "east": 126.1, "north": 28.3},
        }
    ]


def test_cwa_binary_content_type_is_sniffed_and_redirects_are_allowlisted() -> None:
    assert _sniff_image_media_type(
        b"\x89PNG\r\n\x1a\nfixture",
        declared_media_type="application/octet-stream",
        url="https://cwaopendata.s3.ap-northeast-1.amazonaws.com/Observation/O-A0058-006.png",
    ) == "image/png"
    assert _sniff_image_media_type(
        b"\xff\xd8\xfffixture",
        declared_media_type="binary/octet-stream",
        url="https://cwaopendata.s3.ap-northeast-1.amazonaws.com/Observation/O-B0030-003.jpg",
    ) == "image/jpeg"
    _validate_cwa_redirect(
        "https://opendata.cwa.gov.tw/fileapi/source",
        "https://opendata.cwa.gov.tw/fileapi/target",
        authenticated=True,
    )
    with pytest.raises(ValueError, match="redirect"):
        _validate_cwa_redirect(
            "https://opendata.cwa.gov.tw/fileapi/source",
            "https://127.0.0.1/internal",
            authenticated=True,
        )
    _validate_cwa_redirect(
        "https://opendata.cwa.gov.tw/fileapi/source",
        "https://cwaopendata.s3.ap-northeast-1.amazonaws.com/object",
        authenticated=True,
    )


def test_history_selection_spans_full_window_with_bounded_frames() -> None:
    items = [
        {"sourceTimestamp": f"2026-07-{day:02d}T00:00:00Z"}
        for day in range(1, 31)
    ]

    selected = _evenly_spaced(items, 24)

    assert len(selected) == 24
    assert selected[0] == items[0]
    assert selected[-1] == items[-1]


def test_explicit_frame_limit_cannot_exceed_server_budget(tmp_path: Path) -> None:
    registry = build_cwa_imagery_registry()
    spec = registry["radar.integrated.taiwan.transparent"]
    history = [
        {
            "sourceTimestamp": f"2026-07-11T{index // 6:02d}:{(index % 6) * 10:02d}:00Z",
            "url": spec.latest_url,
        }
        for index in range(30)
    ]
    ingestor = CwaRadarIngestor(
        registry=registry,
        cache=WeatherImageryTileCache(tmp_path / "cache"),
        latest_metadata_fetcher=lambda _spec: history[-1],
        history_metadata_fetcher=lambda _spec, _hours: history,
        bytes_fetcher=_bytes_fetcher,
    )

    frames = ingestor.ingest_recent(
        spec.product_id,
        hours=12,
        allow_network_fetch=True,
        max_frames=10_000,
        build_display_asset=False,
    )

    assert len(frames) == 24


def test_recent_frames_accumulate_from_bounded_rolling_cache(tmp_path: Path) -> None:
    registry = build_cwa_imagery_registry()
    spec = registry["radar.integrated.taiwan.transparent"]
    timestamps = iter(("2026-07-11T03:10:00Z", "2026-07-11T03:20:00Z"))
    active = {"timestamp": next(timestamps)}
    cache = WeatherImageryTileCache(tmp_path / "cache")
    ingestor = CwaRadarIngestor(
        registry=registry,
        cache=cache,
        latest_metadata_fetcher=lambda _spec: {
            "sourceTimestamp": active["timestamp"],
            "url": spec.latest_url,
        },
        history_metadata_fetcher=lambda _spec, _hours: [],
        bytes_fetcher=_bytes_fetcher,
    )

    first = ingestor.ingest_recent(
        spec.product_id,
        hours=3,
        allow_network_fetch=True,
        build_display_asset=False,
    )
    active["timestamp"] = next(timestamps)
    second = ingestor.ingest_recent(
        spec.product_id,
        hours=3,
        allow_network_fetch=True,
        build_display_asset=False,
    )

    assert [frame.source_timestamp for frame in first] == ["2026-07-11T03:10:00Z"]
    assert [frame.source_timestamp for frame in second] == [
        "2026-07-11T03:10:00Z",
        "2026-07-11T03:20:00Z",
    ]


def test_history_failure_degrades_to_latest_with_safe_observable_status(
    tmp_path: Path,
    caplog,
) -> None:
    registry = build_cwa_imagery_registry()
    spec = registry["radar.integrated.taiwan.transparent"]
    ingestor = CwaRadarIngestor(
        registry=registry,
        cache=WeatherImageryTileCache(tmp_path / "cache"),
        latest_metadata_fetcher=lambda _spec: {
            "sourceTimestamp": "2026-07-11T03:20:00Z",
            "url": spec.latest_url,
        },
        history_metadata_fetcher=lambda _spec, _hours: (_ for _ in ()).throw(
            RuntimeError("provider unavailable with sensitive URL")
        ),
        bytes_fetcher=_bytes_fetcher,
    )

    frames = ingestor.ingest_recent(
        spec.product_id,
        hours=3,
        allow_network_fetch=True,
        build_display_asset=False,
    )

    assert [frame.source_timestamp for frame in frames] == ["2026-07-11T03:20:00Z"]
    assert "cwa_imagery_history_status=unavailable" in caplog.text
    assert "sensitive URL" not in caplog.text


def test_configured_true_color_uses_direct_timestamp_adapter(
    tmp_path: Path,
    monkeypatch,
) -> None:
    url = "https://satimage.cwa.gov.tw/example/true-color.jpg"
    registry = build_cwa_imagery_registry(true_color_urls={"taiwan": url})
    monkeypatch.setattr(
        "cwa_radar_ingestor.fetch_cwa_direct_image_metadata",
        lambda spec, timeout_s: {
            "sourceTimestamp": "2026-07-11T03:20:00+00:00",
            "url": spec.latest_url,
        },
    )
    monkeypatch.setattr(
        "cwa_radar_ingestor.fetch_cwa_image_bytes",
        lambda _url, timeout_s: (b"fixture-jpeg", "image/jpeg", "etag"),
    )
    ingestor = CwaSatelliteIngestor.from_cwa_opendata(
        registry=registry,
        cache=WeatherImageryTileCache(tmp_path / "cache"),
    )

    frame = ingestor.ingest_latest(
        "satellite.true_color.taiwan",
        allow_network_fetch=True,
        build_display_asset=False,
    )

    assert frame.image_type == "true_color"
    assert frame.source_timestamp == "2026-07-11T03:20:00+00:00"
