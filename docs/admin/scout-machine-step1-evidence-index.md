# Scout Machine Step 1 Evidence Index

Date: 2026-05-20

Target evidence root:
`/data/scout/deployments`

This index records the evidence chain for the first Scout machine Step 1 runtime
deployment.

## Evidence Directories

### Deployment Takeover

Directory:
`/data/scout/deployments/20260520T031746Z`

Purpose:

- baseline container and image capture;
- rollback tag creation;
- Step 1 image promotion;
- compose recreate of `scout-runtime`;
- read-only post-deploy smoke.

Key files:

- `docker-ps.before.txt`
- `docker-ps.after.txt`
- `docker-images.before.txt`
- `docker-images.after.txt`
- `docker-images.after-rollback-tag.txt`
- `docker-compose.pi.before.yml`
- `docker-compose.pi.deployed.yml`
- `scout-runtime.inspect.before.json`
- `scout-runtime.inspect.after.json`
- `health.before.json`
- `health.after.json`
- `runtime-status.before.json`
- `runtime-status.after.json`
- `providers-status.before.json`
- `providers-status.after.json`

Repo summary:

- `docs/admin/scout-runtime-deployment-takeover.md`

### Hardware-Export Fixture Smoke

Directory:
`/data/scout/deployments/fixture-observation-20260520T033354Z`

Purpose:

- first operator-approved fixture `POST /safety/observations`;
- plumbing-only ingest proof with hardware-export field names.

Key result:

- `observations_processed`: `0 -> 1`
- `safety_level`: `L0_NORMAL -> L0_NORMAL`
- no new incident files

Key files:

- `manual_observation_smoke.request.json`
- `safety-observations.response.json`
- `fixture-observation-summary.json`
- `runtime-status.before.json`
- `runtime-status.after.json`
- `incidents.before.txt`
- `incidents.after.txt`

Repo summary:

- `docs/admin/scout-runtime-fixture-observation-smoke.md`

### Canonical Fixture Target Smoke

Directory:
`/data/scout/deployments/canonical-fixture-observation-20260520T035132Z`

Purpose:

- canonical SensorLog fixture target smoke;
- route-aware ingest proof;
- capability availability proof.

Key result:

- `observations_processed`: `1 -> 2`
- `checkpoint_hits`: `0 -> 1`
- checkpoint: `cp_01`
- available capabilities: `gps`, `gps_horizontal_accuracy`, `imu`, `battery`,
  `pedometer_distance`, `pedometer_steps`
- no new incident files

Key files:

- `manual_observation_smoke.canonical.request.json`
- `safety-observations.response.json`
- `canonical-fixture-observation-summary.json`
- `runtime-status.before.json`
- `runtime-status.after.json`
- `providers-status.before.json`
- `providers-status.after.json`
- `incidents.before.txt`
- `incidents.after.txt`

Repo summaries:

- `docs/admin/scout-runtime-canonical-fixture-local-dry-run.md`
- `docs/admin/scout-runtime-canonical-fixture-target-smoke.md`

### Phase 4 Admin Preview Smoke

Directory:
`/home/alexwang0315/scout-fusion-phase4-admin-auth`

Purpose:

- separate LAN-visible Phase 4 admin preview service;
- verify `/admin/pretrip` returns a map-bearing page from the Scout machine;
- verify mock read-only assistant status/query on port `9110`;
- keep the field runtime on port `9099`.

Key result:

- `scout-pi-phase4-admin`: healthy
- admin preview port: `9110 -> 9099`
- admin auth: `required=true`, `token_source=file`,
  `token_value_exposed=false`
- `GET /admin/pretrip`: HTTP `200` when authenticated, `id="map"` present
- unauthenticated `GET /admin/pretrip`: HTTP `401`
- `GET /assistant/status`: `provider=mock`, `token_values_exposed=false`
- `POST /assistant/query`: `read_only=true`, `model_interpretation=true`
- `GET /runtime/streams/status-read-only` on field runtime: HTTP `404`; the
  repo route remains opt-in with `SCOUT_RUNTIME_STREAM_STATUS_ENABLED=1`
- `GET /admin/tiles/osm/5/26/13.png`: HTTP `200`, fallback tile response
- `GET /admin/tiles/imagery/chilai_nanhua_day1/imagery/5/26/13.png`: HTTP
  `200`, fallback imagery response
- `POST /admin/pretrip/projects/chilai_nanhua_day1/review-decisions` with
  `persist_to_workspace=false`: HTTP `200`, preview-only, no workspace write
- workspace creation POST was not executed because it intentionally writes a
  local workspace and is not idempotent
- `GET /runtime/streams/status-read-only` on the field runtime returned HTTP
  `404`, so the status-only runtime stream surface was not enabled on hardware
  in this smoke
- no `/safety/*` mutation, outbound send, local model request, or hardware
  provider control

Repo summary:

- `docs/admin/scout-machine-phase4-admin-preview-smoke.md`

## Current Runtime Snapshot

Last read-only check in this slice:

- `scout-runtime` image id: `761115bf441b`
- `scout-runtime` status: healthy
- `scout-pi-phase4-admin` status: healthy on `9110`
- `scout-ollama` present but not queried or changed
- `/health`: `status=ok`
- `/runtime/status`: `observations_processed=2`
- `/runtime/status`: `checkpoint_hits=1`
- `/runtime/status`: `safety_level=L0_NORMAL`
- `/providers/status`: provider contract `fixture_or_degraded_step1`
- `/providers/status`: every provider `control_allowed=false`

## Boundary Notes

- Evidence files must not contain passwords, tokens, API keys, or authorization
  values.
- Step 1 evidence does not prove live hardware streaming.
- Step 1 evidence does not prove local model fallback.
- Step 1 evidence does not prove outbound/SOS/SMS/satellite delivery.
- Step 1 evidence does not permit assistant, runtime stream, GPIO, or provider control paths.
