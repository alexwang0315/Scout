# Scout Runtime Fixture Observation Smoke

Date: 2026-05-20

Target: `scout.local`

Smoke id: `20260520T033354Z`

Evidence directory on target:
`/data/scout/deployments/fixture-observation-20260520T033354Z`

## Scope

This smoke intentionally executed one operator-approved fixture
`POST /safety/observations` against the deployed `scout-runtime`.

中文註釋：這是受控 fixture mutation smoke，用來證明 runtime ingest path 能接受一筆
觀測資料；不是現場任務啟動，不是真硬體資料串流，也不是 outbound/SOS 流程。

## Preconditions

- `scout-runtime` was healthy on `9099`.
- deployed image id: `761115bf441b`
- `SCOUT_RUNTIME_PROFILE=pi-field`
- `SCOUT_ENABLE_LIVE_HARDWARE=0`
- `SCOUT_ENABLE_AI_INFERENCE=0`
- `SCOUT_ENABLE_LOCAL_MODEL=0`
- `SCOUT_EVENT_BUS=none`
- provider contract: `fixture_or_degraded_step1`
- all providers reported `control_allowed=false`

## Request

Fixture used:

`/home/alexwang0315/scout-fusion-runtime-b41f50cd/tests/fixtures/hardware/manual_observation_smoke.example.json`

The request was copied into the evidence directory as:

`manual_observation_smoke.request.json`

## Result

The endpoint returned:

- HTTP/curl exit: `0`
- response status: `accepted`
- observations accepted: `1`
- response safety level: `L0_NORMAL`
- response safety events: `[]`
- incident ids: `[]`
- stored incident paths: `[]`

Runtime status before/after:

- `observations_processed`: `0 -> 1`
- `safety_level`: `L0_NORMAL -> L0_NORMAL`
- `checkpoint_hits`: `0`
- `segment_capsules`: `0`
- `incident_packages`: `0`
- persisted `stored_incidents`: `1` before and after, from the existing
  2026-05-19 incident file

Incident file diff:

- no new incident files

## Boundaries Preserved

- no outbound/SOS/SMS/satellite send;
- no local model request;
- no live hardware provider control;
- no runtime stream or remote provider send path;
- no GPIO endpoint;
- no Phase 2 Brain or HumanReview write.

## Limitation

The current fixture proves the ingest endpoint and runtime state transition, but
its SensorLog key names use hardware-export style suffixes such as
`locationLatitude(WGS84)` and `batteryLevel(%)`. The current runtime adapter
accepts the payload but reports those capabilities as unavailable because it
expects canonical keys such as `locationLatitude` and `batteryLevel`.

中文註釋：這次 smoke 是 runtime plumbing proof，不是 route matching / capability
availability proof。下一個硬體資料 slice 應該改成 canonical SensorLog fixture 或在 adapter
明確支援這些硬體匯出欄位。

## Rollback Criteria

Rollback would have been required if any of the following occurred:

- endpoint failed;
- `observations_processed` did not increase by exactly `1`;
- safety level changed away from `L0_NORMAL`;
- response returned incident ids or stored incident paths;
- incident directory gained new files.

No rollback was required.
