# Route Context Field Atlas Demo

## Status And Scope

**WORKING PROTOTYPE** for historical/cultural Route Context and a local RGB
observation workflow. The multispectral/hyperspectral comparison and learned
model results remain **not executed**, not simulated.

Requested workspace: `dongqing_batongguan_historic_trail_newImport`.
The page and server are isolated from Dashboard, Navigation and GIS workers.
Nothing is written into the workspace, canonical briefing, model runtime or
safety truth. No automatic refresh, external model call or new paid API is used.

## Demonstrated Capabilities

- Real primary GPX: 5,649 points, 89,827.14 m recomputed with the existing
  `geo_utils.haversine_m`; segment boundaries remain disconnected. Recording
  dates are displayed in Asia/Taipei. Heights are GPX observations with unknown
  vertical datum, not a new DEM result.
- Six historical editions (1904, 1916, 1924, 1956, 1966, 2001), synchronized
  with NLSC imagery and an adjustable comparison boundary. All imagery comes
  from the selected workspace's existing cache. Edition dates are not
  acquisition dates or evidence of the original historical route's geometry.
- Source-backed historical, cultural and natural context, with topic filters
  and source metadata. The September 7 closure record is explicitly an old
  snapshot; this demonstration does not recheck present access conditions.
- Seven named candidates. Only the public Dashuiku candidate can be located.
  The other six respect cultural-review policy: coordinates, chainage and
  private source links are removed from the HTTP response, not merely hidden.
- Actual GPX elevation profile with a linked route-position selector.
- Human RGB observations: choose a map location or the map center, assign a
  class, write a note, explicitly save to browser localStorage, reload, locate,
  delete or download JSON. Storage is isolated by project ID and GPX SHA-256.
- Observation exports preserve `independent_ground_truth: false`,
  `evaluation_eligible: false`, `runtime_safety_truth: false` and the imagery
  manifest hash. Nearest-vertex chainage is approximate; observations are not
  snapped to the route and an off-route distance is provided.
- Model-readiness view reports the actual GEE `missing_credentials` state and
  zero raw feature records. It does not turn 599 placeholder segments into
  successful observations, a paired dataset, or classification scores.

## Run Locally

From `/home/alexwang0315/work/scout-fusion`:

```bash
./venv/bin/python -B tools/scout_route_context_demo_app.py \
  --project-root /home/alexwang0315/workspace/dongqing_batongguan_historic_trail_newImport \
  --port 19130
```

The server binds only `127.0.0.1`. Use an unused experiment port; do not replace
the existing Dashboard or worker processes. Normal foreground execution stops
with Ctrl-C. There is no automatic startup or permanent background monitor.

The live demo was launched as its own detached Python process with log
`/tmp/scout-route-context-demo.log`. Its PID is reported during the task, not
hard-coded as a reusable stop command.

## Mac Access

A temporary SSH reverse forward binds Mac loopback port 19130 to Scout loopback
port 19130. The Mac returned HTTP 200 and `open` successfully requested Chrome.
No claim is made about subsequent tab focus or user navigation.

```bash
open -a "Google Chrome" 'http://127.0.0.1:19130/'
```

When re-establishing the connection, first ensure the Mac port is free. On Scout:

```bash
ssh -i /home/alexwang0315/.ssh/scout-to-mac \
  -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes \
  -o UserKnownHostsFile=/home/alexwang0315/.ssh/known_hosts \
  -o ConnectTimeout=10 -o ExitOnForwardFailure=yes -f -N \
  -R 127.0.0.1:19130:127.0.0.1:19130 \
  alexwang0315@Lamb780722de-MacBook-Pro.local
```

## Verification

```bash
./venv/bin/python -m pytest -q tests/test_scout_route_context_demo.py
node --check docs/admin/experiments/route-context/app.mjs
node --check tools/scout_route_context_demo_smoke.cjs
node tools/scout_route_context_demo_smoke.cjs http://127.0.0.1:19130 \
  /tmp/scout-route-context-smoke
```

- Focused Python tests cover source binding, parsed-byte receipts, GPX segment
  breaks, sensitivity policy, symlink escape, HTTP origin/host/method boundaries,
  tile allowlisting, no fabricated research scores and no workspace mutations.
- Real Playwright Chromium 1.60.0 checks 1440/1920 desktop and 390/320 mobile
  widths, endpoint framing, canvas pixels, every historical edition, topic and
  source interactions, candidate selection, profile selection, GPX toggling,
  draft save/export/reload/delete, escaped user text and layout overflow.
- The browser smoke uses an isolated browser profile; test observations are
  deleted after verification. It injects a read-only state handle solely for
  camera assertions; the served application has no global debug handle.
- Final smoke has zero page errors and zero external browser requests. The
  result JSON records tile-response counts and sampled canvas colors, not
  scientific accuracy metrics.
- Generated local evidence is at
  `/home/alexwang0315/.codex/visualizations/2026/09/11/scout-route-context-demo/`.
  It includes desktop/mobile screenshots, a sample JSON export and the receipt.
  These private, generated artifacts are not committed to the repository.
- Node was absent from PATH, so Node 24.8.0 arm64 was downloaded to `/tmp` and
  checked against the official SHA-256 manifest. No system Node, production
  dependency or Python venv was upgraded. Existing Playwright/browser caches
  were reused. Lucide is a version-pinned, demo-local vendor asset.
- Navigation guard could not run: both `rtk` and
  `tools/verify_navigation_freeze.py` are absent in this checkout. No guard or
  baseline was created, modified or bypassed. This is **unavailable**, not PASS.
- Shared 32-layer verification is **not applicable**: no import, layer contract,
  shared map path, Navigation output or GIS worker is changed.
- Broad unrelated suites and production hardening were intentionally not run.
  Ruff is not installed or configured in this checkout. The focused Python
  run reports an existing Starlette/AnyIO deprecation warning.

## Next Research Step

Pair actual dated reflectance scenes over this extent, preserve sensor band and
native-resolution metadata, register and mask them, and collect independent
labels without consulting the tested model or treating these RGB drafts as
gold truth. Hold out spatial blocks before training. Only then compare an
RGB baseline, a multispectral model and a hyperspectral model on the same
valid regions and independently labeled test split, with ablations and error
maps. The present page has no spectral-pairing or training endpoint.

Promotion debt includes workspace-version pinning for raw tile bytes, reviewed
cultural-story associations, permissions for distributing imagery, integration
with existing Route Context state, and audited annotation-dataset promotion.
No such promotion is implied by a successful local demonstration.
