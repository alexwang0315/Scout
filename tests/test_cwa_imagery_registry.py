from cwa_imagery_registry import (
    ANIMATION_WINDOWS_HOURS,
    build_cwa_imagery_registry,
    public_registry_contract,
)


def test_registry_covers_requested_radar_satellite_products_and_windows() -> None:
    registry = build_cwa_imagery_registry()

    radar = [item for item in registry.values() if item.family == "radar"]
    satellite = [item for item in registry.values() if item.family == "satellite"]

    assert ANIMATION_WINDOWS_HOURS == (3, 6, 9, 12)
    assert {item.image_type for item in radar} >= {
        "echo_no_terrain",
        "echo_terrain",
        "rainfall_radar",
    }
    assert {item.image_type for item in satellite} >= {
        "visible",
        "color",
        "enhanced_color",
        "black_white",
        "true_color",
    }
    assert {item.extent for item in satellite} >= {
        "full_disk",
        "east_asia",
        "taiwan",
    }
    assert all(item.expected_delay_minutes > 0 for item in registry.values())
    assert all(item.bbox_wgs84.west < item.bbox_wgs84.east for item in registry.values())


def test_public_registry_redacts_upstream_urls_and_secrets() -> None:
    payload = public_registry_contract(build_cwa_imagery_registry())

    assert payload["artifactKind"] == "cwaImageryRegistry"
    assert payload["animationWindowsHours"] == [3, 6, 9, 12]
    assert payload["processingBoundary"]["serverSideOnly"] is True
    assert payload["processingBoundary"]["raspberryPiImageProcessing"] is False
    assert payload["processingBoundary"]["mobileImageProcessing"] is False
    assert "Authorization" not in str(payload)
    assert "latestUrl" not in str(payload)
    assert all("datasetId" in item for item in payload["products"])
