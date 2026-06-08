from __future__ import annotations

from ble_scan_provider import parse_btmgmt_find, server_signal_snapshot_from_ble_scan


def test_parse_btmgmt_find_preserves_ble_rssi_and_address_type() -> None:
    output = """
hci0 type 7 discovering on
Discovery started
hci0 dev_found: 5C:34:75:85:1E:1D type LE Random rssi -40 flags 0x0000
AD flags 0x1a
eir_len 30
hci0 dev_found: 49:B5:AD:19:08:7C type LE Random rssi -65 flags 0x0000
AD flags 0x1a
eir_len 17
hci0 dev_found: F1:BB:A7:9D:9B:A0 type LE Random rssi -66 flags 0x0004
AD flags 0x00
eir_len 8
"""

    snapshot = parse_btmgmt_find(output, captured_at="2026-05-20T00:00:00+00:00")

    assert snapshot.source == "btmgmt"
    assert snapshot.controller == "hci0"
    assert len(snapshot.devices) == 3
    assert snapshot.devices[0].address == "5c:34:75:85:1e:1d"
    assert snapshot.devices[0].address_type == "LE Random"
    assert snapshot.devices[0].rssi_dbm == -40
    assert snapshot.devices[0].flags == "0x0000"
    assert snapshot.devices[0].ad_flags == "0x1a"
    assert snapshot.devices[0].eir_len == 30
    assert snapshot.strongest_device is not None
    assert snapshot.strongest_device.address == "5c:34:75:85:1e:1d"


def test_btmgmt_snapshot_payload_is_radio_evidence_not_identity_claim() -> None:
    snapshot = parse_btmgmt_find(
        """
hci0 dev_found: 5C:34:75:85:1E:1D type LE Random rssi -40 flags 0x0000
AD flags 0x1a
eir_len 30
hci0 dev_found: 49:B5:AD:19:08:7C type LE Random rssi -65 flags 0x0000
AD flags 0x1a
eir_len 17
""",
        captured_at="2026-05-20T00:00:00+00:00",
    )

    payload = server_signal_snapshot_from_ble_scan(snapshot)

    assert payload["source"] == "pi_ble_scan.btmgmt"
    assert payload["evidence_kind"] == "ble_proximity_scan"
    assert payload["identity_stability"] == "unknown_for_random_addresses"
    assert payload["strongest_address"] == "5c:34:75:85:1e:1d"
    assert payload["strongest_rssi_dbm"] == -40
    assert payload["device_count"] == 2
    assert payload["devices"][0]["source"] == "btmgmt"


def test_empty_btmgmt_output_yields_empty_snapshot() -> None:
    snapshot = parse_btmgmt_find("", captured_at="2026-05-20T00:00:00+00:00")

    assert snapshot.controller == "hci0"
    assert snapshot.devices == ()
    assert snapshot.strongest_device is None
