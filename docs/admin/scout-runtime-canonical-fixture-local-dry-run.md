# Scout Runtime Canonical Fixture Local Dry Run

Date: 2026-05-20

Fixture:
`tests/fixtures/hardware/manual_observation_smoke.canonical.example.json`

## Scope

This slice upgrades the hardware smoke fixture from hardware-export field names
to canonical SensorLog field names and proves it against a local temporary
`scout_pi_runtime` app.

中文註釋：這一步只在本機 temporary runtime 裡執行 `/safety/observations`，不再對
`scout.local` 做 target mutation。

## Canonical Keys

The fixture now uses adapter-recognized keys:

- `locationLatitude`
- `locationLongitude`
- `locationHorizontalAccuracy`
- `accelerometerAccelerationX`
- `accelerometerAccelerationY`
- `accelerometerAccelerationZ`
- `batteryLevel`
- `pedometerDistance`
- `pedometerNumberOfSteps`

It intentionally does not use the previous hardware-export suffix keys:

- `locationLatitude(WGS84)`
- `batteryLevel(%)`

## Local Dry Run Result

Expected local result:

- status: `passed`
- safety level: `L0_NORMAL`
- observations delta: `1`
- checkpoint hit delta: `1`
- checkpoint: `cp_01`
- incident files: `0`

Capabilities expected as available:

- `gps`
- `gps_horizontal_accuracy`
- `imu`
- `battery`
- `pedometer_distance`
- `pedometer_steps`

## Boundaries

- target network calls: none
- target `/safety/*` mutation: none
- local temporary runtime mutation: one fixture POST
- outbound/SOS/SMS/satellite: none
- local model: not started
- hardware provider control: none

## Next Slice

If this local dry-run stays green, the next deploy slice can run the canonical
fixture once against `scout.local`, using the same rollback criteria as the
previous fixture observation smoke.

## Follow-Up Target Smoke

2026-05-20: the canonical fixture was run once against `scout.local`.

Result:

- `observations_processed` moved from `1` to `2`;
- `checkpoint_hits` moved from `0` to `1`;
- checkpoint `cp_01` was hit;
- required capabilities were available;
- `safety_level` stayed `L0_NORMAL`;
- no incident ids, stored incident paths, or new incident files were produced.

Detailed evidence:

- `/data/scout/deployments/canonical-fixture-observation-20260520T035132Z`
- `docs/admin/scout-runtime-canonical-fixture-target-smoke.md`
