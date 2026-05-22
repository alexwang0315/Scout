# Scout Phase 4.6 Pi Admin Debug Topology

Date: 2026-05-21

Status: `admin_debug_topology_ready`

## Objective

Make the operator-facing live replay debug surface run from Scout hardware:

```text
IMU / GPX / PDR replay source
  -> scout.local:9099 runtime stream ingest
  -> Pi-side projector writes shared debug JSONL
  -> scout.local:9110/admin/debug reads the same debug JSONL
```

中文註釋：Mac local `/admin/debug` 仍可作為開發 fallback，但 live rehearsal 的
主要觀察面應該是 `scout.local:9110/admin/debug`，避免 operator 以為本機
projection 就是 Scout 機器端狀態。

## Admin Runtime

The Phase 4 admin container now has an opt-in debug projection surface:

- `SCOUT_DEBUG_API_ENABLED=true`;
- `SCOUT_DEBUG_LOG_PATH=/data/scout/admin/debug/runtime-debug-events.jsonl`;
- `GET /admin/debug`;
- `GET /debug/events`;
- `GET /debug/state`;
- `GET /debug/messages`;
- `POST /debug/clear`.

All protected admin/debug routes remain behind the existing Phase 4 admin auth
middleware:

- Basic username: `scout-admin`;
- bearer token or Basic password source:
  `/data/scout/admin/secrets/phase4-admin-token`;
- token value is never embedded in docs, logs, or evidence summaries.

## Projector Placement

Preferred live rehearsal placement:

```bash
docker exec scout-pi-phase4-admin python /app/phase46_live_replay_debug_projector.py \
  --stream-status-url http://172.21.0.1:9099/runtime/streams/status \
  --runtime-status-url http://172.21.0.1:9099/runtime/status \
  --output-jsonl /data/scout/admin/debug/runtime-debug-events.jsonl \
  --session-id debug_session.phase46_live_replay.pi \
  --mission-id mission.normal_climb \
  --poll-count 150 \
  --interval-seconds 1 \
  --replace
```

For the current live container split, `172.21.0.1:9099` is the admin container's
host gateway back to the live runtime port. If the Docker network changes, use
the admin container's gateway address from `docker inspect scout-pi-phase4-admin`
and keep the output path unchanged.

## Operator Flow

1. Open `http://scout.local:9110/admin/debug` with admin auth.
2. Press `Clear` to clear projected debug events only.
3. Start the Pi-side projector.
4. Start the operator-approved replay sender.
5. Watch the timeline or `API` tab for:
   - `observation_ingested`;
   - `route_progress_evaluated`;
   - accepted count changes;
   - observations processed changes;
   - incident delta.

`Clear` only truncates the debug projection log. It does not clear runtime state,
safety state, incidents, outbound queues, Phase 2 Brain, or hardware state.

## Boundaries

Allowed:

- admin debug reads projected runtime status events;
- admin debug clears the projection log;
- replay source can live on Mac or Scout Pi;
- projector can run on Scout Pi or any host that writes the Pi shared debug log.

Not allowed:

- no automatic SOS send;
- no SMS send;
- no satellite send;
- no remote provider send;
- no hardware control action;
- no stream control mutation;
- no Phase 2 Brain writeback;
- no raw payload embedded in docs;
- no secret value embedded in docs.

## Acceptance

Focused checks:

```bash
venv/bin/python -m pytest \
  tests/test_phase4_hardware_admin_preview.py \
  tests/test_debug_api.py \
  tests/test_debug_page.py
```

Hardware smoke criteria:

- unauthenticated `GET http://scout.local:9110/admin/debug` returns `401`;
- authenticated `GET http://scout.local:9110/admin/debug` returns `200`;
- authenticated `GET http://scout.local:9110/debug/events` returns projected events;
- pressing `Clear` changes debug event count to `0`;
- replay live-send after clear creates new `observation_ingested` events.
