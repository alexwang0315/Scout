import unittest

from observation_adapter import (
    CapabilityStatus,
    sensorlog_payload_to_observations,
    sensorlog_record_to_observation,
)


class ObservationAdapterTests(unittest.TestCase):
    def test_apple_watch_sensorlog_record_becomes_observation_with_capabilities(self):
        observation = sensorlog_record_to_observation(
            {
                "loggingTime": "2026-05-11T08:52:12.450+08:00",
                "locationLatitude": "25.063521",
                "locationLongitude": "121.653987",
                "locationAltitude": "34.382206",
                "locationHorizontalAccuracy": "14.0",
                "heartRateBPM": "111.000000",
                "pedometerDistance": "32.4",
                "pedometerNumberOfSteps": "48",
                "accelerometerAccelerationX": "0.277191",
                "batteryLevel": "0.82",
            },
            device="apple_watch",
        )

        self.assertEqual(observation.source, "live_sensorlog")
        self.assertEqual(observation.lat, 25.063521)
        self.assertEqual(observation.lon, 121.653987)
        self.assertEqual(observation.elevation_m, 34.382206)
        self.assertEqual(observation.gps_horizontal_accuracy_m, 14.0)
        self.assertEqual(observation.timestamp, 1778460732.45)
        capabilities = observation.raw["capabilities"]
        self.assertEqual(capabilities["gps"]["status"], CapabilityStatus.AVAILABLE)
        self.assertEqual(capabilities["imu"]["status"], CapabilityStatus.AVAILABLE)
        self.assertEqual(capabilities["heart_rate"]["status"], CapabilityStatus.AVAILABLE)
        self.assertEqual(capabilities["pedometer_distance"]["status"], CapabilityStatus.AVAILABLE)
        self.assertEqual(capabilities["battery"]["status"], CapabilityStatus.AVAILABLE)
        self.assertEqual(capabilities["wifi_rssi"]["status"], CapabilityStatus.UNAVAILABLE_BY_PLATFORM)
        self.assertEqual(capabilities["cellular_rssi"]["status"], CapabilityStatus.UNKNOWN)

    def test_iphone_wifi_rssi_absence_is_platform_capability_not_error(self):
        observation = sensorlog_record_to_observation(
            {
                "locationLatitude": "25.0",
                "locationLongitude": "121.0",
                "locationHorizontalAccuracy": "8.0",
            },
            device="iphone",
            received_at=123.0,
        )

        self.assertEqual(observation.timestamp, 123.0)
        self.assertEqual(
            observation.raw["capabilities"]["wifi_rssi"]["status"],
            CapabilityStatus.UNAVAILABLE_BY_PLATFORM,
        )
        self.assertIsNone(observation.raw["capabilities"]["wifi_rssi"]["value"])

    def test_server_wifi_scan_can_be_attached_as_separate_capability(self):
        snapshot = {"best_ssid": "trailhead-ap", "best_rssi": -61}
        observation = sensorlog_record_to_observation(
            {"locationLatitude": "25.0", "locationLongitude": "121.0"},
            server_signal_snapshot=snapshot,
        )

        capability = observation.raw["capabilities"]["server_wifi_scan"]
        self.assertEqual(capability["status"], CapabilityStatus.AVAILABLE)
        self.assertEqual(capability["value"], snapshot)
        self.assertEqual(observation.raw["server_signal_snapshot"], snapshot)

    def test_payload_with_imu_data_list_converts_each_record(self):
        observations = sensorlog_payload_to_observations(
            {
                "imu_data": [
                    {"locationLatitude": "25.0", "locationLongitude": "121.0"},
                    {"locationLatitude": "25.1", "locationLongitude": "121.1"},
                ]
            },
            received_at=99.0,
        )

        self.assertEqual(len(observations), 2)
        self.assertEqual([observation.lat for observation in observations], [25.0, 25.1])
        self.assertEqual([observation.timestamp for observation in observations], [99.0, 99.0])

    def test_missing_gps_still_yields_observation_with_unavailable_gps(self):
        observation = sensorlog_record_to_observation(
            {"heartRateBPM": "102", "accelerometerAccelerationX": "0.1"},
            received_at=88.0,
        )

        self.assertIsNone(observation.lat)
        self.assertIsNone(observation.lon)
        self.assertEqual(observation.timestamp, 88.0)
        self.assertEqual(observation.raw["capabilities"]["gps"]["status"], CapabilityStatus.UNAVAILABLE)
        self.assertEqual(observation.raw["capabilities"]["heart_rate"]["status"], CapabilityStatus.AVAILABLE)


if __name__ == "__main__":
    unittest.main()
