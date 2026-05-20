# Scout Live Runtime Rollback Drill

Date: 2026-05-20

Target: `scout.local`

Current production URL: `http://scout.local:9099`

## Scope

This is a documentation-only rollback drill for the current live runtime
deployment.

中文註釋：本 slice 沒有實際 rollback。Production 仍維持
`scout-pi-runtime-live` on `9099`。這份文件只固定 rollback 步驟、證據目錄、
驗證條件與停止條件。

## Current Live State

Current production runtime:

- container: `scout-pi-runtime-live`;
- image: `scout-fusion/pi-runtime:live`;
- port: `9099 -> 9099`;
- runtime profile: `pi-field-live`;
- compose directory: `/home/alexwang0315/scout-fusion-live`;
- compose file: `docker-compose.pi.live.yml`.

Rollback target:

- container: `scout-pi-runtime`;
- image: `scout-fusion/pi-runtime:local`;
- port: `9099 -> 9099`;
- expected runtime profile: `pi-field`;
- compose directory: `/home/alexwang0315/scout-fusion-runtime`;
- compose file: `docker-compose.pi.yml`.

Rollback image tag from cutover:

- `scout-fusion/pi-runtime:rollback-before-live-20260520T100435Z`.

Cutover evidence directory:

- `/data/scout/deployments/live-cutover-20260520T100435Z`.

## Evidence Directory

If rollback is actually executed later, create a new evidence directory:

```bash
ROLLBACK_ID="$(date -u +%Y%m%dT%H%M%SZ)"
ROLLBACK_DIR="/data/scout/deployments/live-rollback-${ROLLBACK_ID}"
mkdir -p "${ROLLBACK_DIR}"
```

Evidence directory pattern:
`/data/scout/deployments/live-rollback-${ROLLBACK_ID}`

Capture pre-rollback evidence:

```bash
docker ps --format '{{.Names}}|{{.Image}}|{{.Status}}|{{.Ports}}' > "${ROLLBACK_DIR}/docker-ps.before.txt"
curl --max-time 10 -sS http://127.0.0.1:9099/health > "${ROLLBACK_DIR}/health.before.json"
curl --max-time 10 -sS http://127.0.0.1:9099/assistant/status > "${ROLLBACK_DIR}/assistant-status.before.json"
curl --max-time 10 -sS http://127.0.0.1:9099/runtime/streams/status-read-only > "${ROLLBACK_DIR}/runtime-stream-status.before.json"
```

## Rollback Command Sequence

Stop live runtime before starting deterministic Step 1:

```bash
cd /home/alexwang0315/scout-fusion-live
docker compose -f docker-compose.pi.live.yml stop scout-live

cd /home/alexwang0315/scout-fusion-runtime
docker tag scout-fusion/pi-runtime:rollback-before-live-20260520T100435Z scout-fusion/pi-runtime:local
docker compose -f docker-compose.pi.yml up -d --no-build scout
```

Verify rollback:

```bash
curl --max-time 10 -sS http://127.0.0.1:9099/health > "${ROLLBACK_DIR}/health.after.json"
docker ps --format '{{.Names}}|{{.Image}}|{{.Status}}|{{.Ports}}' > "${ROLLBACK_DIR}/docker-ps.after.txt"
```

Expected rollback verification:

- `/health` returns `status=ok`;
- `/health` returns `runtime_profile=pi-field`;
- `SCOUT_ENABLE_LIVE_HARDWARE=0`;
- `SCOUT_ENABLE_AI_INFERENCE=0`;
- `SCOUT_ENABLE_LOCAL_MODEL=0`;
- `runtime_stream_transport_enabled` is absent or false;
- `remote_provider_live_send_enabled` is absent or false;
- `hardware_provider_control_enabled` is absent or false.

## Restore Live After A Drill

If a controlled rollback drill is executed and the operator wants to restore
live runtime:

```bash
cd /home/alexwang0315/scout-fusion-runtime
docker compose -f docker-compose.pi.yml stop scout

cd /home/alexwang0315/scout-fusion-live
docker compose -f docker-compose.pi.live.yml up -d --no-build scout-live
```

Verify restore:

- `/health` returns `status=ok`;
- `/health` returns `runtime_profile=pi-field-live`;
- `/assistant/status` returns `read_only=true`;
- `/runtime/streams/status-read-only` returns `read_only_surface=true`;
- provider-control status returns `allowed_actions=[read_provider_status]`;
- token values remain hidden.

## Boundary

This documentation drill did not perform:

- no container stop;
- no production rollback;
- no production restore;
- no new observation;
- no stream control mutation;
- no remote provider send;
- no Telegram send;
- no SOS send;
- no SMS send;
- no satellite send;
- no hardware control action;
- no Phase 2 Brain writeback;
- no ObservedFact write;
- no HumanReview or review decision mutation.

Rollback remains an operator-only action. Assistant responses, runtime stream
events, provider status, and hardware provider records must not trigger rollback
automatically.
