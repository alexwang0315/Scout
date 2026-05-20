# Scout Runtime Deployment Takeover

Date: 2026-05-20

Target: `scout.local`

Deployment id: `20260520T031746Z`

Evidence directory on target:
`/data/scout/deployments/20260520T031746Z`

## Scope

This deployment took ownership of the existing `scout-runtime` service on the
Scout machine. It did not deploy local model inference, live hardware providers,
runtime streams, outbound transports, SOS, SMS, or satellite integrations.

中文註釋：這是 deterministic Pi Step 1 runtime 部署接管，不是 field mission
activation，也不是 AI/local-model path 啟用。

## Baseline

Before takeover:

- container: `scout-runtime`
- image tag: `scout-fusion/pi-runtime:local`
- image id: `def19b12ef9a`
- status: healthy
- compose project: `scout-fusion-runtime`
- compose file: `/home/alexwang0315/scout-fusion-runtime/docker-compose.pi.yml`
- port: `9099`
- data root: `/data/scout`

Rollback image tag created:

- `scout-fusion/pi-runtime:rollback-20260520T031746Z`

## Deployed Runtime

The already-built Step 1 image was promoted into the service tag:

- source image tag: `scout-fusion/pi-runtime:step1`
- deployed service tag: `scout-fusion/pi-runtime:local`
- deployed image id: `761115bf441b`
- container: `scout-runtime`
- restart policy: `unless-stopped`
- published port: `9099`

The compose environment now includes the Step 1 boundary flags:

- `SCOUT_RUNTIME_PROFILE=pi-field`
- `SCOUT_ENABLE_LIVE_HARDWARE=0`
- `SCOUT_ENABLE_AI_INFERENCE=0`
- `SCOUT_ENABLE_LOCAL_MODEL=0`
- `SCOUT_EVENT_BUS=none`
- `SCOUT_AI_FALLBACK_MODE=offline_only`
- `SCOUT_SAFETY_ENABLED=true`

## Verification

Remote and local read-only probes passed:

- `GET /health`
- `GET /runtime/status`
- `GET /providers/status`

Observed post-deploy fields:

- `status=ok`
- `safety_runtime_enabled=true`
- `step1_blockers=[]`
- `live_hardware_enabled=false`
- `ai_inference_enabled=false`
- `local_model_enabled=false`
- `event_bus=none`
- provider contract: `fixture_or_degraded_step1`
- provider `control_allowed=false`

## State Boundary

Not performed:

- no `POST /safety/observations`;
- no other `/safety/*` mutation;
- no outbound/SOS/SMS/satellite send;
- no local model request;
- no hardware provider control;
- no runtime stream or remote provider send path.

The incident directory still contained only the existing
`incident_route_deviation_1826.json` file from 2026-05-19 during the post-deploy
check.

## Rollback

Rollback command class:

```bash
cd /home/alexwang0315/scout-fusion-runtime
docker tag scout-fusion/pi-runtime:rollback-20260520T031746Z scout-fusion/pi-runtime:local
docker compose -f docker-compose.pi.yml up -d --no-build --force-recreate scout
```

Rollback should be followed by the same read-only probes:

- `GET /health`
- `GET /runtime/status`
- `GET /providers/status`
