from __future__ import annotations

from collections.abc import Mapping

from cwa_imagery_registry import ANIMATION_WINDOWS_HOURS, ImageryProductSpec
from cwa_radar_ingestor import (
    BytesFetcher,
    HistoryFetcher,
    MetadataFetcher,
    _ingest_metadata_item,
    _ingest_metadata_items,
    _merge_recent_cached_frames,
    _optional_history_metadata,
    DEFAULT_CWA_JOB_MAX_FRAMES_PER_PRODUCT,
    _product,
    _require_network_approval,
    _utc_now,
)
from weather_imagery_tile_cache import CachedImageryFrame, WeatherImageryTileCache


class CwaSatelliteIngestor:
    def __init__(
        self,
        *,
        registry: Mapping[str, ImageryProductSpec],
        cache: WeatherImageryTileCache,
        latest_metadata_fetcher: MetadataFetcher,
        history_metadata_fetcher: HistoryFetcher,
        bytes_fetcher: BytesFetcher,
    ) -> None:
        self.registry = dict(registry)
        self.cache = cache
        self.latest_metadata_fetcher = latest_metadata_fetcher
        self.history_metadata_fetcher = history_metadata_fetcher
        self.bytes_fetcher = bytes_fetcher

    @classmethod
    def from_cwa_opendata(
        cls,
        *,
        registry: Mapping[str, ImageryProductSpec],
        cache: WeatherImageryTileCache,
        env: Mapping[str, str] | None = None,
        timeout_s: float = 30.0,
    ) -> "CwaSatelliteIngestor":
        from cwa_radar_ingestor import (
            fetch_cwa_direct_image_metadata,
            fetch_cwa_history_image_metadata,
            fetch_cwa_image_bytes,
            fetch_cwa_latest_image_metadata,
        )

        return cls(
            registry=registry,
            cache=cache,
            latest_metadata_fetcher=lambda spec: (
                fetch_cwa_latest_image_metadata(spec, env=env, timeout_s=timeout_s)
                if spec.dataset_id
                else fetch_cwa_direct_image_metadata(spec, timeout_s=timeout_s)
            ),
            history_metadata_fetcher=lambda spec, hours: fetch_cwa_history_image_metadata(
                spec,
                hours=hours,
                env=env,
                timeout_s=timeout_s,
            ),
            bytes_fetcher=lambda url: fetch_cwa_image_bytes(url, timeout_s=timeout_s),
        )

    def ingest_latest(
        self,
        product_id: str,
        *,
        allow_network_fetch: bool = False,
        fetched_at: str | None = None,
        dimensions: tuple[int, int] = (0, 0),
        build_display_asset: bool = True,
    ) -> CachedImageryFrame:
        spec = _product(self.registry, product_id, "satellite")
        _require_network_approval(allow_network_fetch)
        return _ingest_metadata_item(
            spec,
            self.latest_metadata_fetcher(spec),
            cache=self.cache,
            bytes_fetcher=self.bytes_fetcher,
            fetched_at=fetched_at or _utc_now(),
            dimensions=dimensions,
            build_display_asset=build_display_asset,
        )

    def ingest_recent(
        self,
        product_id: str,
        *,
        hours: int,
        allow_network_fetch: bool = False,
        fetched_at: str | None = None,
        dimensions: tuple[int, int] = (0, 0),
        build_display_asset: bool = True,
        max_frames: int | None = None,
    ) -> list[CachedImageryFrame]:
        spec = _product(self.registry, product_id, "satellite")
        _require_network_approval(allow_network_fetch)
        if hours not in ANIMATION_WINDOWS_HOURS:
            raise ValueError(f"unsupported animation window: {hours}")
        ingested = _ingest_metadata_items(
            spec,
            [
                *_optional_history_metadata(self.history_metadata_fetcher, spec, hours),
                self.latest_metadata_fetcher(spec),
            ],
            cache=self.cache,
            bytes_fetcher=self.bytes_fetcher,
            fetched_at=fetched_at or _utc_now(),
            dimensions=dimensions,
            build_display_asset=build_display_asset,
            max_frames=(
                min(DEFAULT_CWA_JOB_MAX_FRAMES_PER_PRODUCT, max(0, int(max_frames)))
                if max_frames is not None
                else min(
                    DEFAULT_CWA_JOB_MAX_FRAMES_PER_PRODUCT,
                    int(hours * 60 / max(1, spec.update_interval_minutes)) + 2,
                )
            ),
        )
        return _merge_recent_cached_frames(
            self.cache,
            spec,
            ingested,
            hours=hours,
            max_frames=(
                min(DEFAULT_CWA_JOB_MAX_FRAMES_PER_PRODUCT, max(0, int(max_frames)))
                if max_frames is not None
                else DEFAULT_CWA_JOB_MAX_FRAMES_PER_PRODUCT
            ),
        )
