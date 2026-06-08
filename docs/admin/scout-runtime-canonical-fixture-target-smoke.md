# Scout Runtime Canonical Fixture Target Smoke

Date: 2026-05-20

Target: `scout.local`

Smoke id: `20260520T035132Z`

Evidence directory on target:
`/data/scout/deployments/canonical-fixture-observation-20260520T035132Z`

## Scope

This smoke executed one canonical SensorLog fixture
`POST /safety/observations` against the deployed `scout-runtime` on the Scout
machine.

中文註釋：這是第二次受控 target mutation smoke。它驗證 route-aware ingest 與
capability interpretation，不是真硬體 streaming，也不是現場任務啟動。

## Preconditions

- `scout-runtime` was healthy on `9099`.
- `SCOUT_RUNTIME_PROFILE=pi-field`
- `SCOUT_ENABLE_LIVE_HARDWARE=0`
- `SCOUT_ENABLE_AI_INFERENCE=0`
- `SCOUT_ENABLE_LOCAL_MODEL=0`
- `SCOUT_EVENT_BUS=none`
- provider contract: `fixture_or_degraded_step1`
- every provider reported `control_allowed=false`

## Request

Fixture copied to the target evidence directory:

`manual_observation_smoke.canonical.request.json`

The fixture used canonical SensorLog keys, including:

- `locationLatitude`
- `locationLongitude`
- `locationHorizontalAccuracy`
- `accelerometerAccelerationX`
- `accelerometerAccelerationY`
- `accelerometerAccelerationZ`
- `batteryLevel`
- `pedometerDistance`
- `pedometerNumberOfSteps`

## Result

The endpoint returned:

- HTTP/curl exit: `0`
- response status: `accepted`
- observations accepted: `1`
- response safety level: `L0_NORMAL`
- checkpoint ids: `cp_01`
- incident ids: `[]`
- stored incident paths: `[]`

Runtime status before/after:

- `observations_processed`: `1 -> 2`
- `checkpoint_hits`: `0 -> 1`
- `safety_level`: `L0_NORMAL -> L0_NORMAL`
- `segment_capsules`: `0`
- `incident_packages`: `0`
- persisted `stored_incidents`: `1` before and after, from the existing
  2026-05-19 incident file

Available capabilities:

- `gps`
- `gps_horizontal_accuracy`
- `imu`
- `battery`
- `pedometer_distance`
- `pedometer_steps`

Incident file diff:

- no new incident files

## Boundaries Preserved

- no outbound/SOS/SMS/satellite send;
- no local model request;
- no live hardware provider control;
- no runtime stream or remote provider send path;
- no GPIO endpoint;
- no Phase 2 Brain or HumanReview write.

`scout-ollama` remained present on the machine but was not queried or changed.

## Rollback Criteria

Rollback would have been required if any of the following occurred:

- endpoint failed;
- `observations_processed` did not increase by exactly `1`;
- checkpoint `cp_01` was not hit;
- required capabilities were not available;
- safety level changed away from `L0_NORMAL`;
- response returned incident ids or stored incident paths;
- incident directory gained new files;
- any provider reported `control_allowed=true`.

No rollback was required.
