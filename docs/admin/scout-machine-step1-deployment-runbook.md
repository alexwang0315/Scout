# Scout Machine Step 1 Deployment Runbook

Date: 2026-05-20

Target: `scout.local`

Service: `scout-runtime`

Compose project: `scout-fusion-runtime`

Compose file:
`/home/alexwang0315/scout-fusion-runtime/docker-compose.pi.yml`

## Purpose

This runbook freezes the Step 1 deployment path that was validated on the Scout
machine. It is for deterministic Pi runtime deployment and evidence replay only.

中文註釋：這不是 field mission activation，不是 local model deployment，不是 live
hardware provider enablement，也不是 outbound/SOS/SMS/satellite flow。

## Current Known Good State

- container: `scout-runtime`
- image tag: `scout-fusion/pi-runtime:local`
- image id: `761115bf441b`
- rollback tag: `scout-fusion/pi-runtime:rollback-20260520T031746Z`
- rollback image id: `def19b12ef9a`
- status: healthy
- published port: `9099`
- runtime profile: `pi-field`
- data root: `/data/scout`
- incident store: `/data/scout/incidents`
- `observations_processed=2`
- `checkpoint_hits=1`
- `safety_level=L0_NORMAL`

## Required Environment

The service must keep these Step 1 flags:

- `SCOUT_RUNTIME_PROFILE=pi-field`
- `SCOUT_ENABLE_LIVE_HARDWARE=0`
- `SCOUT_ENABLE_AI_INFERENCE=0`
- `SCOUT_ENABLE_LOCAL_MODEL=0`
- `SCOUT_EVENT_BUS=none`
- `SCOUT_AI_FALLBACK_MODE=offline_only`
- `SCOUT_SAFETY_ENABLED=true`

## Step 1 Deployment Sequence

1. Capture baseline state.

```bash
DEPLOY_ID=$(date -u +%Y%m%dT%H%M%SZ)
DEPLOY_DIR=/data/scout/deployments/$DEPLOY_ID
mkdir -p "$DEPLOY_DIR"
docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.ID}}\t{{.Status}}\t{{.Ports}}' > "$DEPLOY_DIR/docker-ps.before.txt"
docker inspect scout-runtime > "$DEPLOY_DIR/scout-runtime.inspect.before.json"
curl --max-time 5 http://127.0.0.1:9099/health > "$DEPLOY_DIR/health.before.json"
curl --max-time 5 http://127.0.0.1:9099/runtime/status > "$DEPLOY_DIR/runtime-status.before.json"
curl --max-time 5 http://127.0.0.1:9099/providers/status > "$DEPLOY_DIR/providers-status.before.json"
```

2. Create rollback image tag before replacing the service tag.

```bash
docker tag scout-fusion/pi-runtime:local scout-fusion/pi-runtime:rollback-$DEPLOY_ID
```

3. Promote the Step 1 image and recreate only `scout-runtime`.

```bash
docker tag scout-fusion/pi-runtime:step1 scout-fusion/pi-runtime:local
cd /home/alexwang0315/scout-fusion-runtime
docker compose -f docker-compose.pi.yml up -d --no-build --force-recreate scout
```

4. Wait for health and run read-only probes.

```bash
docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' scout-runtime
curl --max-time 5 http://127.0.0.1:9099/health
curl --max-time 5 http://127.0.0.1:9099/runtime/status
curl --max-time 5 http://127.0.0.1:9099/providers/status
```

5. Only after operator approval, run one fixture observation smoke.

```bash
curl --max-time 5 -X POST http://127.0.0.1:9099/safety/observations \
  -H 'Content-Type: application/json' \
  --data @manual_observation_smoke.canonical.request.json
```

## Rollback

Rollback command class:

```bash
cd /home/alexwang0315/scout-fusion-runtime
docker tag scout-fusion/pi-runtime:rollback-20260520T031746Z scout-fusion/pi-runtime:local
docker compose -f docker-compose.pi.yml up -d --no-build --force-recreate scout
```

After rollback, rerun:

- `GET /health`
- `GET /runtime/status`
- `GET /providers/status`

## Stop Conditions

Stop and rollback if any of these occur:

- `/health` is not `ok`;
- `step1_blockers` is not empty;
- `SCOUT_ENABLE_LIVE_HARDWARE`, `SCOUT_ENABLE_AI_INFERENCE`, or
  `SCOUT_ENABLE_LOCAL_MODEL` is enabled;
- `SCOUT_EVENT_BUS` is not `none`;
- any provider reports `control_allowed=true`;
- safety level changes away from `L0_NORMAL` during fixture smoke;
- fixture smoke returns incident ids or stored incident paths;
- `/data/scout/incidents` gains an unexpected new file;
- any flow tries to send outbound/SOS/SMS/satellite.

## Boundaries

- Do not query or control `scout-ollama` for Step 1.
- Do not enable local model fallback.
- Do not start k3s, MQTT, NATS, Coral, Jetson, or satellite integrations.
- Do not use assistant responses to control runtime, providers, or hardware.
- Do not write Phase 2 Brain, ObservedFact, HumanReview, or review decision.
- Do not store passwords, tokens, or API keys in evidence files.

## Evidence Index

The frozen evidence index is:

`docs/admin/scout-machine-step1-evidence-index.md`
