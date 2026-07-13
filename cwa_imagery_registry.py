from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Mapping


ANIMATION_WINDOWS_HOURS = (3, 6, 9, 12)
ALLOWED_CWA_IMAGE_HOSTS = frozenset(
    {
        "cwaopendata.s3.ap-northeast-1.amazonaws.com",
        "opendata.cwa.gov.tw",
        "satimage.cwa.gov.tw",
    }
)


@dataclass(frozen=True)
class Wgs84Bounds:
    west: float
    south: float
    east: float
    north: float

    def to_dict(self) -> dict[str, float]:
        return {
            "west": self.west,
            "south": self.south,
            "east": self.east,
            "north": self.north,
        }


@dataclass(frozen=True)
class ImageryProductSpec:
    product_id: str
    family: Literal["radar", "satellite"]
    dataset_id: str | None
    image_type: str
    extent: Literal["large", "taiwan", "full_disk", "east_asia"]
    bbox_wgs84: Wgs84Bounds
    update_interval_minutes: int
    expected_delay_minutes: int
    latest_url: str | None
    media_type: str
    sampling_role: Literal["risk", "visual", "corroborating"]
    history_supported: bool = True
    available: bool = True
    georeference_version: str = "cwa_registry_affine_wgs84.v1"
    map_overlay_supported: bool = True
    route_sampling_supported: bool = True

    def to_public_dict(self) -> dict[str, object]:
        return {
            "productId": self.product_id,
            "family": self.family,
            "datasetId": self.dataset_id,
            "imageType": self.image_type,
            "extent": self.extent,
            "bboxWgs84": self.bbox_wgs84.to_dict(),
            "updateIntervalMinutes": self.update_interval_minutes,
            "expectedDelayMinutes": self.expected_delay_minutes,
            "mediaType": self.media_type,
            "samplingRole": self.sampling_role,
            "historySupported": self.history_supported,
            "available": self.available,
            "georeferenceVersion": self.georeference_version,
            "mapOverlaySupported": self.map_overlay_supported,
            "routeSamplingSupported": self.route_sampling_supported,
            "upstreamUrlEmbedded": False,
            "secretValueEmbedded": False,
        }


def _latest(dataset_id: str, extension: str) -> str:
    return (
        "https://cwaopendata.s3.ap-northeast-1.amazonaws.com/Observation/"
        f"{dataset_id}.{extension}"
    )


def build_cwa_imagery_registry(
    *,
    true_color_urls: Mapping[str, str] | None = None,
) -> dict[str, ImageryProductSpec]:
    products: dict[str, ImageryProductSpec] = {}
    radar_products = (
        ("radar.integrated.large.no_terrain", "O-A0058-001", "echo_no_terrain", "large", Wgs84Bounds(115.0, 17.75, 126.5, 29.25), "visual"),
        ("radar.integrated.large.terrain", "O-A0058-002", "echo_terrain", "large", Wgs84Bounds(115.0, 17.75, 126.5, 29.25), "visual"),
        ("radar.integrated.taiwan.no_terrain", "O-A0058-003", "echo_no_terrain", "taiwan", Wgs84Bounds(118.0, 20.5, 124.0, 26.5), "risk"),
        ("radar.integrated.taiwan.terrain", "O-A0058-004", "echo_terrain", "taiwan", Wgs84Bounds(118.0, 20.5, 124.0, 26.5), "visual"),
        ("radar.integrated.large.transparent", "O-A0058-005", "echo_no_terrain", "large", Wgs84Bounds(115.0, 17.75, 126.5, 29.25), "risk"),
        ("radar.integrated.taiwan.transparent", "O-A0058-006", "echo_no_terrain", "taiwan", Wgs84Bounds(118.0, 20.5, 124.0, 26.5), "risk"),
        ("radar.rainfall.shulin", "O-A0084-001", "rainfall_radar", "taiwan", Wgs84Bounds(119.9, 23.6, 122.9, 26.4), "corroborating"),
        ("radar.rainfall.nantun", "O-A0084-002", "rainfall_radar", "taiwan", Wgs84Bounds(119.1, 22.7, 122.1, 25.5), "corroborating"),
        ("radar.rainfall.linyuan", "O-A0084-003", "rainfall_radar", "taiwan", Wgs84Bounds(118.9, 21.1, 121.9, 23.9), "corroborating"),
    )
    for product_id, dataset_id, image_type, extent, bbox, role in radar_products:
        products[product_id] = ImageryProductSpec(
            product_id=product_id,
            family="radar",
            dataset_id=dataset_id,
            image_type=image_type,
            extent=extent,  # type: ignore[arg-type]
            bbox_wgs84=bbox,
            update_interval_minutes=2 if dataset_id.startswith("O-A0084") else 10,
            expected_delay_minutes=8 if dataset_id.startswith("O-A0084") else 12,
            latest_url=_latest(dataset_id, "png"),
            media_type="image/png",
            sampling_role=role,  # type: ignore[arg-type]
            georeference_version=(
                "cwa_source_metadata_affine_wgs84_required.v1"
                if dataset_id.startswith("O-A0084")
                else "cwa_registry_affine_wgs84.v1"
            ),
        )

    satellite_families = {
        "color": "O-B0028",
        "black_white": "O-B0029",
        "enhanced_color": "O-B0030",
        "visible": "O-B0031",
    }
    extents = {
        "full_disk": ("001", Wgs84Bounds(60.0, -90.0, 240.0, 90.0)),
        "east_asia": ("002", Wgs84Bounds(70.0, 0.0, 160.0, 60.0)),
        "taiwan": ("003", Wgs84Bounds(117.0, 19.0, 126.0, 27.0)),
    }
    for image_type, prefix in satellite_families.items():
        for extent, (suffix, bbox) in extents.items():
            dataset_id = f"{prefix}-{suffix}"
            product_id = f"satellite.{image_type}.{extent}"
            products[product_id] = ImageryProductSpec(
                product_id=product_id,
                family="satellite",
                dataset_id=dataset_id,
                image_type=image_type,
                extent=extent,  # type: ignore[arg-type]
                bbox_wgs84=bbox,
                update_interval_minutes=10,
                expected_delay_minutes=20,
                latest_url=_latest(dataset_id, "jpg"),
                media_type="image/jpeg",
                sampling_role=(
                    "risk"
                    if image_type == "enhanced_color" and extent == "taiwan"
                    else "visual"
                    if extent == "full_disk"
                    else "corroborating"
                ),
                georeference_version=(
                    "cwa_himawari_fixed_grid_reprojection_required.v1"
                    if extent == "full_disk"
                    else "cwa_source_metadata_affine_wgs84_preferred.v1"
                ),
                map_overlay_supported=True,
                route_sampling_supported=extent != "full_disk",
            )

    configured_true_color = dict(true_color_urls or {})
    for extent, (_suffix, bbox) in extents.items():
        latest_url = configured_true_color.get(extent)
        product_id = f"satellite.true_color.{extent}"
        products[product_id] = ImageryProductSpec(
            product_id=product_id,
            family="satellite",
            dataset_id=None,
            image_type="true_color",
            extent=extent,  # type: ignore[arg-type]
            bbox_wgs84=bbox,
            update_interval_minutes=10,
            expected_delay_minutes=20,
            latest_url=latest_url,
            media_type="image/jpeg",
            sampling_role="corroborating",
            history_supported=False,
            available=bool(latest_url),
            georeference_version=(
                "cwa_himawari_fixed_grid_reprojection_required.v1"
                if extent == "full_disk"
                else "cwa_satellite_portal_adapter_required.v1"
            ),
            map_overlay_supported=True,
            route_sampling_supported=False,
        )
    return products


def public_registry_contract(
    registry: Mapping[str, ImageryProductSpec],
) -> dict[str, object]:
    return {
        "artifactKind": "cwaImageryRegistry",
        "schemaVersion": "cwaImageryRegistry.v1",
        "provider": "cwa_opendata",
        "animationWindowsHours": list(ANIMATION_WINDOWS_HOURS),
        "products": [registry[key].to_public_dict() for key in sorted(registry)],
        "processingBoundary": {
            "serverSideOnly": True,
            "raspberryPiImageProcessing": False,
            "mobileImageProcessing": False,
            "clientCredentialAllowed": False,
            "candidateOnly": True,
            "runtimeSafetyTruth": False,
        },
    }
