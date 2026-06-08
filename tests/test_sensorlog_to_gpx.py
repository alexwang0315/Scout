import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from sensorlog_to_gpx import sensorlog_json_to_gpx


GPX_NS = {"g": "http://www.topografix.com/GPX/1/1"}
SCOUT_NS = {"scout": "https://scout-fusion.local/gpx/extensions/1"}


class SensorLogToGpxTests(unittest.TestCase):
    def test_converts_location_and_extensions(self):
        with tempfile.TemporaryDirectory() as tmp:
            input_path = Path(tmp) / "sample.json"
            output_path = Path(tmp) / "sample.gpx"
            input_path.write_text(json.dumps([
                {
                    "loggingTime": "2026-05-11T08:52:12.450+08:00",
                    "locationLatitude": "25.063521",
                    "locationLongitude": "121.653987",
                    "locationAltitude": "34.382206",
                    "locationHorizontalAccuracy": "14.0",
                    "heartRateBPM": "111.000000",
                    "accelerometerAccelerationX": "0.277191",
                }
            ]))

            count = sensorlog_json_to_gpx(input_path, output_path, track_name="test track")

            self.assertEqual(count, 1)
            root = ET.parse(output_path).getroot()
            points = root.findall(".//g:trkpt", GPX_NS)
            self.assertEqual(len(points), 1)
            self.assertEqual(points[0].attrib["lat"], "25.06352100")
            self.assertEqual(points[0].findtext("g:ele", namespaces=GPX_NS), "34.38")
            self.assertEqual(points[0].findtext("g:time", namespaces=GPX_NS), "2026-05-11T00:52:12.450000Z")
            self.assertEqual(
                points[0].findtext(".//scout:heartRateBPM", namespaces=SCOUT_NS),
                "111.000000",
            )

    def test_filters_by_horizontal_accuracy(self):
        with tempfile.TemporaryDirectory() as tmp:
            input_path = Path(tmp) / "sample.json"
            output_path = Path(tmp) / "sample.gpx"
            input_path.write_text(json.dumps([
                {"locationLatitude": "25.0", "locationLongitude": "121.0", "locationHorizontalAccuracy": "8"},
                {"locationLatitude": "25.1", "locationLongitude": "121.1", "locationHorizontalAccuracy": "80"},
            ]))

            count = sensorlog_json_to_gpx(input_path, output_path, max_horizontal_accuracy=20)

            self.assertEqual(count, 1)
            points = ET.parse(output_path).getroot().findall(".//g:trkpt", GPX_NS)
            self.assertEqual(points[0].attrib["lat"], "25.00000000")


if __name__ == "__main__":
    unittest.main()
