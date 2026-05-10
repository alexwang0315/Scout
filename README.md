# S.C.O.U.T. Fusion

S.C.O.U.T. Fusion is a FastAPI prototype that combines macOS Wi-Fi RSSI scanning, mobile IMU/GPS uploads, pedestrian dead reckoning (PDR), and an LLM navigation agent. The goal is to guide a user toward the strongest nearby Wi-Fi signal while recording movement and signal data for maps.

## What It Does

- Scans nearby Wi-Fi networks on macOS with the private `airport -s` command.
- Receives iPhone / Apple Watch / SensorLog IMU, GPS, pedometer, and motion data.
- Updates relative position using PDR from either full IMU samples or legacy distance/heading samples.
- Stores GPS and PDR trajectories in memory for live status and map generation.
- Uses a `pydantic-ai` agent through OpenRouter to generate navigation instructions.
- Aggregates Apple Watch / SensorLog IMU samples into local movement summaries without LLM calls.
- Generates signal heatmaps and GPS/PDR trajectory images.
- Exposes a simple dashboard in `index.html` that polls the server status.

## Project Layout

| File | Purpose |
| --- | --- |
| `server.py` | Main FastAPI server, route registration, background AI worker, map endpoints. |
| `agent.py` | Pydantic AI navigation agent and Wi-Fi scan/move tools. |
| `macos_wifi.py` | macOS Wi-Fi scanner using `airport -s`. |
| `imu_api.py` | `/imu/upload` router for full IMU/GPS SensorLog payloads. |
| `pdr_record.py` | Pydantic model for mobile sensor records. |
| `pdr_engine.py` | PDR engine for IMU-based and distance/heading-based position updates. |
| `sensor_decoder.py` | Decoder for legacy `/pdr/update` SensorLog payloads. |
| `movement_summary.py` | Local Apple Watch / IMU summary extraction and feedback features. |
| `visualize_signal.py` | Signal heatmap generation. |
| `shared_queue.py` | Shared asyncio queue for non-blocking AI decision events. |
| `index.html` | Minimal live dashboard. |

The repository root is the canonical server version. The `Scout/` directory is an older nested copy kept for reference and should not be used as the active server entrypoint unless you intentionally work on that legacy copy.

## Requirements

- macOS, for Wi-Fi scanning via `/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/resources/airport`.
- Python 3.12 is what the current local virtual environment uses.
- OpenRouter API key for `/navigate` and background AI decisions.
- Network access when calling the LLM provider.

Core Python packages used by the current app:

```bash
fastapi
uvicorn
python-dotenv
pydantic
pydantic-ai
matplotlib
numpy
scipy
python-multipart
```

The repository currently includes a local `venv/`, but for a clean setup you should generally create your own virtual environment and install dependencies there.

## Environment

Create `.env` in the repository root:

```bash
SCOUT_DEBUG=true
SCOUT_PORT=9099
OPENROUTER_API_KEY=your_openrouter_key_here
```

Notes:

- `SCOUT_PORT` defaults to `9099` when absent.
- `OPENROUTER_API_KEY` is required for AI navigation routes and worker decisions.
- `.env` is ignored by git and should not be committed.

## Run

From the repository root:

```bash
./venv/bin/python server.py
```

Or with uvicorn directly:

```bash
./venv/bin/uvicorn server:app --host 0.0.0.0 --port 9099
```

If using a custom port:

```bash
SCOUT_PORT=9101 ./venv/bin/python server.py
```

Health check:

```bash
curl http://127.0.0.1:9099/
```

Expected response:

```json
{"status":"S.C.O.U.T. Fusion Online","debug":true,"port":9099}
```

## API Workflow

### 1. Check Server Status

```bash
curl http://127.0.0.1:9099/status
```

Returns the latest pose, strongest Wi-Fi signal, trajectory counters, last instruction, and queued AI events.

### 2. Upload Full IMU/GPS Records

Endpoint:

```http
POST /imu/upload
```

Example:

```bash
curl -X POST http://127.0.0.1:9099/imu/upload \
  -H 'Content-Type: application/json' \
  -d '{
    "motionTimestamp_sinceReboot": 1000000000,
    "accelerometerAccelerationX": 2.0,
    "accelerometerAccelerationY": 0.0,
    "accelerometerAccelerationZ": 0.0,
    "gyroRotationZ": 0.0,
    "locationLatitude": 25.0,
    "locationLongitude": 121.0
  }'
```

Behavior:

- GPS points are added to `gps_trajectory` when latitude and longitude are present.
- IMU data updates `pdr_trajectory` through `update_from_imu()`.

### 3. Upload Legacy Distance/Heading PDR Data

Endpoint:

```http
POST /pdr/update
```

Example:

```bash
curl -X POST http://127.0.0.1:9099/pdr/update \
  -H 'Content-Type: application/json' \
  -d '{"pedometerNumberOfSteps": 2, "motionHeading": 90}'
```

Supported distance fields:

- `pedometerDistance`
- `pedometerNumberOfSteps`
- legacy typo-compatible `pedometerNumberofSteps`

Supported heading fields:

- `motionHeading`
- `locationCourse`

The endpoint updates position and queues an AI decision event without blocking ingestion.

It also accepts `imu_data` arrays from Apple Watch / SensorLog JSON exports. These samples are converted into local movement summaries using fields such as:

- `accelerometerAccelerationX`
- `accelerometerAccelerationY`
- `accelerometerAccelerationZ`
- `motionGravityY`
- `motionTimestamp_sinceReboot`

Movement summaries can be checked without calling the LLM:

```bash
curl http://127.0.0.1:9099/movement-summary
```

### 4. Request Navigation

```bash
curl http://127.0.0.1:9099/navigate
```

This calls the LLM navigation agent. It requires a valid `OPENROUTER_API_KEY`.

### 5. Generate Maps

Signal heatmap:

```bash
curl http://127.0.0.1:9099/generate_map
```

Output file:

```text
heatmap.png
```

Trajectory map:

```bash
curl http://127.0.0.1:9099/trajectory/map
```

Output file:

```text
trajectory_map.png
```

Trajectory counters:

```bash
curl http://127.0.0.1:9099/trajectory/status
```

## Dashboard

Open `index.html` from a browser that can reach the server host. The page polls:

```text
http://<server-host>:9099/status
```

If serving from another machine, make sure the phone/browser can reach the Mac's LAN IP and that macOS firewall allows the port.

## Current Runtime Fixes

This version fixes the main execution blockers from the previous state:

- Restored a complete FastAPI app in `server.py` after it had been reduced to an incomplete worker snippet.
- Added FastAPI lifespan startup/shutdown handling for the background AI worker.
- Added `PDREngine.update_position()` so `/pdr/update` works with the current PDR engine.
- Added missing `time` import in `pdr_engine.py`.
- Updated SensorLog step-field parsing to support `pedometerNumberOfSteps`.
- Updated Pydantic v2 model config and replaced deprecated `dict()` usage.
- Made `SCOUT_PORT` effective instead of hardcoding the runtime port.
- Merged the legacy `Scout/server.py` Apple Watch movement-summary flow into the root `server.py`.

## Verification Commands

Syntax check:

```bash
./venv/bin/python -m py_compile agent.py imu_api.py macos_wifi.py movement_summary.py pdr_engine.py pdr_record.py sensor_decoder.py server.py shared_queue.py visualize_signal.py
```

Import and route check:

```bash
./venv/bin/python - <<'PY'
import server
print('import ok')
print(sorted(route.path for route in server.app.routes))
PY
```

Temporary live server check:

```bash
SCOUT_PORT=9101 ./venv/bin/python server.py
curl http://127.0.0.1:9101/
```

Apple Watch sample check:

```bash
./venv/bin/python server.py
./send_samples.sh PdrSample
curl http://127.0.0.1:9099/movement-summary
```

## Known Notes

- Wi-Fi scanning is macOS-specific and depends on the private `airport` binary path.
- Trajectory state is currently in memory. Restarting the server clears runtime trajectory state.
- Background AI decisions are queued in memory and are not persisted.
- `cert.pem` and `key.pem` appear to be local certificates; verify before using them in production.
- The repository has historical tracked generated files such as `venv/` and `__pycache__/`. They are not ideal for long-term repository hygiene.
