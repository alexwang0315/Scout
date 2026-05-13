# Phase 2 Admin API Future Mount Plan

## Purpose

`phase2_admin_api.py` already exposes a read-only Phase 2 admin preview router,
but it is intentionally not mounted into `server.py` in the current slice. This
plan defines how a future implementation can mount that router without changing
the Phase 1 safety runtime, `admin_api.py`, or the Phase 1 SVG after-action HTML.

The future slice should make persisted Phase 2 Brain data available to local
admin tooling while preserving the Phase 1 trail safety black box as the
deterministic runtime baseline.

## Current State

- `phase2_admin_api.py` provides `create_phase2_admin_router(brain_store_root=...)`.
- The router uses the prefix `/phase2/admin`.
- The first endpoint is `GET /phase2/admin/preview`.
- The endpoint reads from `BrainFileStore` and builds a compact admin preview
  payload from persisted Brain nodes.
- `tests/test_phase2_admin_api.py` already covers direct app and router usage,
  missing Brain refs, and no Brain node writes during preview reads.
- `server.py` currently mounts the IMU router, Phase 1 admin router, and Phase 1
  safety router only.

## Non-Goals

- Do not modify Phase 1 route-progress, alerting, incident recording, or safety
  runtime behavior.
- Do not change `PdrSample`, PDR ingestion, SensorLog decoding, or movement
  summary behavior.
- Do not modify `admin_api.py`.
- Do not modify the Phase 1 admin SVG/HTML surface.
- Do not merge Phase 2 preview payloads into existing Phase 1 admin endpoints.
- Do not add write endpoints for Brain nodes, artifacts, manifests, runtime
  control, or acknowledgement actions.

## Mount Contract

The future implementation should mount the existing Phase 2 router in
`server.py` only when explicitly enabled by configuration.

Proposed environment variables:

- `SCOUT_PHASE2_ADMIN_API_ENABLED`: defaults to `false`.
- `SCOUT_PHASE2_BRAIN_STORE_ROOT`: required when the Phase 2 admin API is
  enabled.

The mount should be equivalent to:

```python
from phase2_admin_api import create_phase2_admin_router

if SCOUT_PHASE2_ADMIN_API_ENABLED:
    app.include_router(
        create_phase2_admin_router(brain_store_root=SCOUT_PHASE2_BRAIN_STORE_ROOT)
    )
```

The final implementation can keep local naming consistent with `server.py`, but
the behavior should remain:

- disabled by default;
- configured by an explicit Brain store root;
- mounted under `/phase2/admin`;
- isolated from Phase 1 routers and runtime state;
- read-only from the perspective of HTTP requests.

## Brain Store Root

`SCOUT_PHASE2_BRAIN_STORE_ROOT` should point at the file-backed Scout Brain root
produced by Phase 2 replay/demo/store workflows. The server mount must pass this
path directly to `create_phase2_admin_router(brain_store_root=...)`.

The future slice should not infer the Brain root from Phase 1 mission graph,
incident store, SVG assets, PDR state, or runtime session objects. The Brain root
is the Phase 2 source of truth for this API, and the mounted router should be
able to serve persisted preview data even when no live Phase 1 runtime event is
currently active.

Recommended local smoke setup:

```bash
/Users/alexwang0315/scout-fusion/venv/bin/python phase2_team_replay_demo.py --store-root /tmp/scout-phase2-brain
SCOUT_PHASE2_ADMIN_API_ENABLED=true SCOUT_PHASE2_BRAIN_STORE_ROOT=/tmp/scout-phase2-brain /Users/alexwang0315/scout-fusion/venv/bin/python server.py
```

## Read-Only Boundary

The mounted Phase 2 API must remain read-only in the future implementation:

- `GET /phase2/admin/preview` may load Brain nodes and artifact references.
- The endpoint must not create, update, delete, or rewrite Brain node files.
- The endpoint must not repair the Brain index as a side effect.
- Missing required Brain references should continue to return a clean 404.
- No Phase 1 runtime object should be passed into the Phase 2 router.

If future admin actions are needed, they should be added behind separate specs
with explicit writeback policy, human-confirm gates, and tests. They should not
be smuggled into this preview mount.

## Phase 1 Isolation

The future mount must preserve Phase 1 behavior:

- `SCOUT_SAFETY_ENABLED` semantics remain unchanged.
- `SCOUT_SAFETY_MISSION_GRAPH`, route progress config, and incident store
  behavior remain unchanged.
- Existing `/admin/*` and `/safety/*` Phase 1 routes keep their payloads and
  handlers.
- The Phase 1 admin SVG/HTML remains the same surface unless a separate UI spec
  explicitly changes it.
- Phase 2 `/phase2/admin/*` routes are additive and namespaced, so no existing
  Phase 1 path is shadowed.

## Future Implementation Steps

1. Add Phase 2 admin configuration parsing in `server.py` near the existing
   server-level environment configuration.
2. Import `create_phase2_admin_router` from `phase2_admin_api.py`.
3. When `SCOUT_PHASE2_ADMIN_API_ENABLED` is true, require
   `SCOUT_PHASE2_BRAIN_STORE_ROOT` to be set to a non-empty path.
4. Include the Phase 2 router with that Brain store root.
5. Log whether the Phase 2 admin API is enabled and which Brain root is being
   used.
6. Add focused tests that create a temporary Brain store, mount `server.app`
   under enabled and disabled configurations, and verify route visibility.
7. Keep existing Phase 1 safety runtime tests unchanged except for ensuring the
   new default-disabled configuration does not alter their expectations.

## Acceptance Criteria

- With no Phase 2 environment variables set, `server.py` exposes no
  `/phase2/admin/preview` route.
- With `SCOUT_PHASE2_ADMIN_API_ENABLED=true` and
  `SCOUT_PHASE2_BRAIN_STORE_ROOT` pointing at a populated Brain store,
  `GET /phase2/admin/preview` returns the same preview payload shape covered by
  `tests/test_phase2_admin_api.py`.
- The future mount reuses `create_phase2_admin_router(brain_store_root=...)`
  instead of duplicating preview logic in `server.py`.
- Preview requests do not mutate Brain node files or the Brain index.
- Missing required Brain references still return 404.
- Existing Phase 1 `/admin/*`, `/safety/*`, `/pdr/update`, `/status`, and root
  endpoints keep their current behavior.
- No Phase 1 SVG/HTML file changes are required for the mount.
- No Phase 1 safety runtime, `PdrSample`, route-progress, or alerting code is
  changed.

## Future Test Commands

Focused Phase 2 API tests:

```bash
/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest tests/test_phase2_admin_api.py
```

Future server mount tests should be added in a focused file, for example:

```bash
/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest tests/test_phase2_admin_api_mount.py
```

Phase 1 regression commands for the future mount slice:

```bash
/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest tests/test_safety_runtime_session.py
/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest tests/test_safety_api.py
/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest tests/test_admin_after_action.py
```

Read-only smoke command after a populated Brain store exists:

```bash
/Users/alexwang0315/scout-fusion/venv/bin/python phase2_team_replay_demo.py --store-root /tmp/scout-phase2-brain
SCOUT_PHASE2_ADMIN_API_ENABLED=true SCOUT_PHASE2_BRAIN_STORE_ROOT=/tmp/scout-phase2-brain /Users/alexwang0315/scout-fusion/venv/bin/python server.py
curl http://127.0.0.1:9099/phase2/admin/preview
```

The implementation should also compare Brain store file listings before and
after the preview request to prove the endpoint remains read-only.
