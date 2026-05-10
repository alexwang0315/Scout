#!/usr/bin/env bash
# Sequential test sender for PDR update (wraps raw Apple Watch JSON array)
API_URL="http://localhost:9099/pdr/update"
DATA_DIR="${1:-./PdrSample}"
if [ ! -d "$DATA_DIR" ]; then
  echo "Directory not found: $DATA_DIR"
  exit 1
fi
for f in "$DATA_DIR"/*.json; do
  if [ -f "$f" ]; then
    echo ">>> Sending $f"
    payload=$(python3 - "$f" <<'PY'
import json
import sys

with open(sys.argv[1], 'r') as fp:
    data = json.load(fp)
if isinstance(data, list):
    payload = {
        'imu_data': data,
        'pedometerDistance': '0',
        'motionHeading': '0'
    }
else:
    payload = {
        'imu_data': data.get('imu_data', []),
        'pedometerDistance': data.get('pedometerDistance', '0'),
        'motionHeading': data.get('motionHeading', '0')
    }
print(json.dumps(payload))
PY
)
    response=$(curl -s -X POST "$API_URL" -H "Content-Type: application/json" -d "$payload")
    echo "Response: $response"
    sleep 0.5
  fi
done
echo "All samples sent."
