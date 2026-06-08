from __future__ import annotations

from wifi_scan_provider import (
    parse_iw_scan,
    parse_nmcli_wifi_list,
    server_signal_snapshot_from_wifi_scan,
    wifi_channel_from_frequency_mhz,
)


def test_parse_iw_scan_preserves_dbm_rssi_and_associated_ap() -> None:
    output = """
BSS ac:9e:17:77:3f:08(on wlan0)
\tfreq: 2437.0
\tsignal: -31.00 dBm
\tSSID: ASUS
BSS 60:83:e7:30:32:92(on wlan0) -- associated
\tfreq: 5785.0
\tsignal: -27.00 dBm
\tSSID: ASUS_5G
BSS ba:83:e7:30:32:94(on wlan0)
\tfreq: 5785.0
\tsignal: -30.00 dBm
\tSSID: \\x00\\x00\\x00
"""

    snapshot = parse_iw_scan(output, captured_at="2026-05-20T00:00:00+00:00")

    assert snapshot.source == "iw"
    assert len(snapshot.access_points) == 3
    strongest = snapshot.strongest_access_point
    assert strongest is not None
    assert strongest.bssid == "60:83:e7:30:32:92"
    assert strongest.ssid == "ASUS_5G"
    assert strongest.signal_dbm == -27.0
    assert strongest.channel == 157
    assert strongest.associated is True
    assert snapshot.access_points[2].ssid is None


def test_parse_nmcli_wifi_list_preserves_signal_percent_as_fallback() -> None:
    output = "\n".join(
        [
            r"60\:83\:E7\:30\:32\:92:ASUS_5G:Infra:157:270 Mbit/s:90:WPA2",
            r"AC\:9E\:17\:77\:3F\:08:ASUS:Infra:6:130 Mbit/s:74:WPA2",
        ]
    )

    snapshot = parse_nmcli_wifi_list(output, captured_at="2026-05-20T00:00:00+00:00")

    assert snapshot.source == "nmcli"
    assert len(snapshot.access_points) == 2
    assert snapshot.access_points[0].bssid == "60:83:e7:30:32:92"
    assert snapshot.access_points[0].channel == 157
    assert snapshot.access_points[0].frequency_mhz == 5785.0
    assert snapshot.access_points[0].signal_percent == 90
    assert snapshot.strongest_access_point is not None
    assert snapshot.strongest_access_point.ssid == "ASUS_5G"


def test_server_signal_snapshot_prefers_dbm_when_available() -> None:
    snapshot = parse_iw_scan(
        """
BSS ac:9e:17:77:3f:08(on wlan0)
\tfreq: 2437.0
\tsignal: -31.00 dBm
\tSSID: ASUS
BSS 60:83:e7:30:32:92(on wlan0) -- associated
\tfreq: 5785.0
\tsignal: -27.00 dBm
\tSSID: ASUS_5G
""",
        captured_at="2026-05-20T00:00:00+00:00",
    )

    payload = server_signal_snapshot_from_wifi_scan(snapshot)

    assert payload["source"] == "pi_wifi_scan.iw"
    assert payload["best_bssid"] == "60:83:e7:30:32:92"
    assert payload["best_ssid"] == "ASUS_5G"
    assert payload["best_rssi_dbm"] == -27.0
    assert payload["best_signal_percent"] is None
    assert payload["access_point_count"] == 2


def test_frequency_to_wifi_channel_mapping() -> None:
    assert wifi_channel_from_frequency_mhz(2437.0) == 6
    assert wifi_channel_from_frequency_mhz(5785.0) == 157
    assert wifi_channel_from_frequency_mhz(2484.0) == 14
    assert wifi_channel_from_frequency_mhz(None) is None
